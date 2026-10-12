import numpy as np
import pandas as pd
from datetime import datetime, date
import itertools


FILE_PATH = "wikiElec.ElecBs3.txt"

active_user_IDs = dict() ## contains every user ID
outcomes_by_ID = dict() ## contains result info by ID: date, time, result
votes_by_ID = dict() ## contains voter info by ID: date, time, vote
nominee_user_IDs = dict() ## dictionary containing nominated users and users who nominated them
nominee_time = dict()
earliest_vote = datetime(year = 2100, month = 1, day = 1, hour = 0, minute = 0, second = 0)

### begin reading data, issue with special characters 

with open(FILE_PATH, errors='ignore') as data_file:
    data_lines = data_file.readlines()
    for line in data_lines:
      if line.startswith("U"): # user being nominated
        nominee_orig_ID = line.split()[2]# update for a new user
        active_user_IDs.setdefault(nominee_orig_ID, line.split()[1])
      elif line.startswith('N'):
        nominator_orig_ID = line.split()[2]
        active_user_IDs.setdefault(nominator_orig_ID, line.split()[1])
      elif line.startswith("V"): # vote on the current user
        voter_orig_ID = line.split()[5] # "from" vertex
        active_user_IDs.setdefault(voter_orig_ID, line.split()[2])

with open(FILE_PATH,errors='ignore') as data_file:
    data_lines = data_file.readlines()

    # Save components of data in three lists kept in synchrony
    from_data = list()
    to_data = list()
    labels = list()
    vote_info = list()
    outcome_info = list()
    early_list = list()
    count = 0
    # Data format:
    # nominee line U <user (nominee) ID> <username> (we want ID)
    # vote line V <outcome> <user (voter) ID> <time> <username>
    nominee_orig_ID = "" # ID of current nominee ("to" vertex)
    outcome = -2 # Outcome of current nominee's vote
    for line in data_lines:
      if line.startswith("E"): # vote outcome section
        earliest_v = datetime.strftime(earliest_vote, '%Y-%m-%d %H:%M:%S')
        earliest_v = [earliest_v] * count
        early_list.append(earliest_v)
        count = 0
        earliest_vote = datetime(year = 2100, month = 1, day = 1, hour = 0, minute = 0, second = 0)
        outcome = line.split()[1] # get outcome of the vote
      elif line.startswith('T'): ## (eric)
        info = line.split()
        decision_date = datetime.strptime(info[1], '%Y-%m-%d')
        decision_time = datetime.strptime(info[2], '%H:%M:%S')
        decision_datetime = datetime.combine(decision_date, datetime.time(decision_time))
        decision_stamp = (decision_datetime, outcome) ## tuple of decision info (eric)
      elif line.startswith("U"): # user being nominated
        nominee_orig_ID = line.split()[2] # pull ID
        outcomes_by_ID.setdefault(nominee_orig_ID, []).append(decision_stamp) # add to dict
      elif line.startswith('N'): ## (eric)
        info = line.split() ## grabbing the whole line
        nominator_ID = info[1] ## taking numeric ID
        nominator_name = info[2] ## taking string ID
        nominator_stamp = (nominator_ID, nominator_name) ## tuple of ID and string
        nominee_user_IDs.setdefault(nominee_orig_ID, nominator_stamp) ## dict with nominee, nominator
      elif line.startswith("V"): # vote on the current user
        # get info
        count += 1
        info = line.split()
        result = info[1] ## vote that was cast
        vote_date = datetime.strptime(info[3], '%Y-%m-%d')
        vote_time = datetime.strptime(info[4], '%H:%M:%S')
        vote_datetime = datetime.combine(vote_date, datetime.time(vote_time))
        voter_orig_ID = info[5] # "from" vertex
        vote_stamp = (vote_datetime, result) ## tuple of all vote info (eric)
        votes_by_ID.setdefault(voter_orig_ID, []).append(vote_stamp) ## has all vote info for each user, ## assigned by ID. (eric)
        if vote_datetime <= earliest_vote:
            earliest_vote = vote_datetime

        # add info
        # note: we added nominee and voter IDs to dict of active IDs
        # so they are guaranteed to exist
        from_data.append(active_user_IDs[voter_orig_ID])
        to_data.append(active_user_IDs[nominee_orig_ID])
        labels.append(result)
        vote_info.append(vote_stamp) ## (eric)
        outcome_info.append(decision_stamp) ## (eric)

    earliest_v = datetime.strftime(earliest_vote, '%Y-%m-%d %H:%M:%S')
    earliest_v = [earliest_v] * count
    early_list.append(earliest_v)
    del(early_list[0])
    early_list = list(itertools.chain(*early_list))

    # Make a (square) adjacency matrix the size of the number of people
    # as given by ID

    data = np.array(labels) ## all of the votes
    ##print(np.min(data), np.max(data))
    row_ind = np.array(from_data) ## all of the voter IDs
    col_ind = np.array(to_data) ## all of the nominee IDs, repeated to match the number of votes on them
    vote_data = np.array(vote_info) ## date, time, vote info (eric)
    outcome_data = np.array(outcome_info) ## date, time, decision info (eric)
    nominee_list = np.array(list(nominee_user_IDs.keys()))
    nominator_data = np.array(list(nominee_user_IDs.values()))
    early_data = np.array(early_list)

    #
    wiki_edges = pd.DataFrame(list(zip(row_ind, col_ind, data)),
                    columns = ['From Node ID', 'To Node ID', 'Edge Weight'])
    wiki_edges = wiki_edges.sort_values(by=['From Node ID'])
    wiki_edges.to_csv("wiki_test_edges.csv", encoding='utf-8', index=False)

    users_tuple_list = [ (active_user_IDs[key], key) for key in active_user_IDs.keys()]
    wiki_users = pd.DataFrame(users_tuple_list, columns = ['Node ID', 'User ID'])
    wiki_users = wiki_users.sort_values(by=['Node ID'])    
    wiki_users.to_csv("wiki_test_users.csv", encoding='utf-8', index=False)