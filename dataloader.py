# OK, TRANSFERRED

import collections
import os.path
import sys
from datetime import datetime

from dataset import PoiDataset, Usage


class PoiDataloader():
    ''' Creates datasets from our prepared Gowalla/Foursquare data files.
    The file consist of one check-in per line in the following format (tab separated):

    <user-id> <timestamp> <latitude> <longitude> <location-id>

    Check-ins for the same user have to be on continous lines.
    Ids for users and locations are recreated and continous from 0.
    '''

    def __init__(self, loc_count, *, max_users: int = 0, min_checkins: int = 0) -> None:
        """max_users limits the amount of users to load.
        min_checkins discards users with less than this amount of checkins.
        """
        self.max_users: int = max_users
        self.min_checkins: int = min_checkins

        # * maps from client_x.txt's UserId to an internal venue ID used by PoiDataloader and PoiDataset.
        self.user2id: dict[int, int] = {}
        # * maps from client_x.txt's VenueId to an internal venue ID used by PoiDataloader and PoiDataset.
        # ! This definition prevents remapping across different clients in a federated setting.
        # ! The preprocessing already made the locations start indexing from 0
        self.poi2id: dict[int, int] = {i: i for i in range(loc_count)}

        self.users: list[int] = []
        self.times: list[list[float]] = []
        self.coords: list[list[tuple[float, float]]] = []
        self.locs: list[list[int]] = []

    def create_dataset(self, sequence_length, batch_size, split, usage=Usage.MAX_SEQ_LENGTH, custom_seq_count=1):
        return PoiDataset(self.users.copy(),\
                          self.times.copy(),\
                          self.coords.copy(),\
                          self.locs.copy(),\
                          sequence_length,\
                          batch_size,\
                          split,\
                          usage,\
                          len(self.poi2id),\
                          custom_seq_count)


    def user_count(self):
        return len(self.users)

    def locations(self):
        return len(self.poi2id)

    def read(self, file):
        if not os.path.isfile(file):
            print('[Error]: Dataset not available: {}. Please follow instructions under ./data/README.md'.format(file))
            sys.exit(1)

        # collect all users with min checkins:
        self.read_users(file)
        # collect checkins for all collected users:
        self.read_pois(file)
        # print(self.user2id)  #* DEBUG SET A

        print(self.user2id)
        # print(self.poi2id)
        assert all(
            [k == v for k, v in self.poi2id.items()]
        ), f"Mapping invalid, results cannot be combined at the federation server: {self.poi2id}"

    def read_users(self, file):
        f = open(file, 'r')
        lines = f.readlines()

        prev_user = int(lines[0].split('\t')[0])
        visit_cnt = 0
        for i, line in enumerate(lines):
            tokens = line.strip().split('\t')
            user = int(tokens[0])
            if user == prev_user:
                visit_cnt += 1
            else:
                if visit_cnt >= self.min_checkins:
                    self.user2id[prev_user] = len(self.user2id)
                #else:
                #    print('discard user {}: to few checkins ({})'.format(prev_user, visit_cnt))
                prev_user = user
                visit_cnt = 1
                if self.max_users > 0 and len(self.user2id) >= self.max_users:
                    break # restrict to max users
        #! Original implementation forgot to consider the last user...
        if visit_cnt >= self.min_checkins:
            self.user2id[prev_user] = len(self.user2id)
        else:
            raise Exception("Pre-processing step did not eliminate user with insufficient checkins. Please run `poetry run python -m project.task.flashback.dataset_preparation` then retry.")
        #    print('discard user {}: to few checkins ({})'.format(prev_user, visit_cnt))

    def read_pois(self, file):
        f = open(file, 'r')
        lines = f.readlines()

        # store location ids
        user_time = []
        user_coord = []
        user_loc = []

        prev_user = int(lines[0].split('\t')[0])
        prev_user = self.user2id.get(prev_user)
        for i, line in enumerate(lines):
            tokens = line.strip().split('\t')
            user = int(tokens[0])
            if self.user2id.get(user) is None:
                continue # user is not of interrest
            user = self.user2id.get(user)

            time = (datetime.strptime(tokens[1], "%Y-%m-%dT%H:%M:%SZ") - datetime(1970, 1, 1)).total_seconds() # unix seconds
            lat = float(tokens[2])
            long = float(tokens[3])
            coord = (lat, long)

            location = int(tokens[4]) # location nr
            if self.poi2id.get(location) is None: # get-or-set locations
                raise Exception(f"Should not occur as poi2id should have been set during __init__(): location={location} not a key in self.poi2id={self.poi2id}")
                self.poi2id[location] = len(self.poi2id)
            location = self.poi2id.get(location)

            if user == prev_user:
                # insert in front!  #* from start to end of list, chronological order (txt file gives descending order)
                user_time.insert(0, time)
                user_coord.insert(0, coord)
                user_loc.insert(0, location)
            else:
                self.users.append(prev_user)
                self.times.append(user_time)
                self.coords.append(user_coord)
                self.locs.append(user_loc)

                # resart:
                prev_user = user
                user_time = [time]
                user_coord = [coord]
                user_loc = [location]

        # process also the latest user in the for loop
        self.users.append(prev_user)
        self.times.append(user_time)
        self.coords.append(user_coord)
        self.locs.append(user_loc)
