import json
import gzip
import pandas as pd
import numpy as np
from sys import argv
import os
######################################################################################################
### Takes amazon core5 or ratings files as json.gz or csv and outputs edges and users csvs
### Note: users beginning with A are reviewers, with B are products
### Outputs users csvs with extra information including:
###     Avg_self: if a reviewer - average rating they gave out overall
###               if a product - average rating they received overall
###     Avg_other: if a reviewer - average rating of all the products they reviewed
###                if a product - average rating given by all the reviewers that reviewed this product
###     Stdev_self: if a reviewer - stdev of all the ratings they gave
###                 if a product - stdev of all the ratings they received
###     Stdev_others: if a reviewer - stdev of the avg_other metric above
###                   if a product - stdev of the avg_other metric above
###     Degree: The number of ratings connected to this user
### USAGE: python <program name> <path to source json or csv file>
######################################################################################################

### Does multiple joins and groupbys to get the avg and stdev columns for the users_df
### returns: the dataframe with the avg and stdev columns properly calculated and placed
def group_and_transform(left_df: pd.DataFrame, avg_df: pd.DataFrame, group1: str, group2: str) -> pd.DataFrame:
    left_df = left_df.groupby([group1, group2]).mean()
    left_df = left_df.join(avg_df, lsuffix = '_real', rsuffix ='_avg')
    left_df_degrees = left_df.reset_index().groupby(group1)[group2].nunique()
    left_df_mean =  left_df.groupby(level=0).mean().filter(['overall_real', 'overall_avg'])
    left_df_stdev = left_df.groupby(level=0).std().filter(['overall_real', 'overall_avg'])
    left_df_mean.columns = ['Avg_self', 'Avg_others']
    left_df_stdev.columns = ['Stdev_self', 'Stdev_others']
    left_df = left_df_mean.join(left_df_stdev)
    left_df = left_df.assign(Degree=left_df_degrees.values)
    left_df = left_df.reset_index()
    left_df = left_df.rename(columns={group1:'User ID'})

    return left_df

### Merges the node IDs contained in the users_dfs with the original_df which has the edge information.
### returns: the edges_df properly formatted
def merge_dfs(grouped_products: pd.DataFrame, grouped_reviewers: pd.DataFrame, original_df: pd.DataFrame) -> pd.DataFrame:
    edges_df_reviewers = original_df.merge(grouped_reviewers, how = 'left', left_on = 'reviewerID', right_on = 'User ID')
    edges_df_products = original_df.merge(grouped_products, how = 'left', left_on = 'asin', right_on = 'User ID')
    edges_df_reviewers = edges_df_reviewers.rename(columns={'Node ID':'From Node ID'})
    edges_df_products = edges_df_products.rename(columns={'Node ID': 'To Node ID', 'overall': 'Weight'})
    edges_df = edges_df_products.join(edges_df_reviewers, lsuffix = '_1', rsuffix = '_2')
    drop_cols = [i for i in edges_df.columns.values if len(i.split('_')) != 1]
    edges_df = edges_df.drop(columns = drop_cols)
    edges_df = edges_df[['From Node ID', 'To Node ID', 'Weight']]
    edges_df['Weight'] = set_weights(edges_df['Weight'].values)
    edges_df = edges_df.astype(int).sort_values(by=['From Node ID'])

    return edges_df

### Vectorized function to turn the weights into 1 if greater than 3, -1 if less than 3, and 0 otherwise.
### returns: the entire column with the proper weight labels.
def set_weights(rating: np.float64) -> np.float64:
    rating = rating/3 -1
    original_sign = rating
    rating = abs(rating)
    rating = np.ceil(rating)
    rating = np.copysign(rating, original_sign)

    return rating

### Loads the gzipped json to dataframe format
### returns: original_df
def open_json(filename: str) -> pd.DataFrame:
    with gzip.open(filename, 'rt', encoding = 'utf-8') as file:
        original_df = pd.read_json(file, orient = 'records', lines = True)

    return original_df

### Loads the source csv to dataframe format
### returns: original_df
def open_csv(filename: str) -> pd.DataFrame:
    with open(filename) as file:
        original_df = pd.read_csv(file, usecols = [0, 1, 2], names = ['reviewerID', 'asin', 'overall'])

    return original_df

### Parses the name for the output csvs
### returns: the parsed filename
def make_csv_name(filename: str) -> str:
    filename = filename.split('.')[0].split('_')
    if filename[0] == "reviews":
        filename = 'amazon' + filename[1] + filename[2] +'_core5'
    elif filename[0] == "ratings":
        filename = 'Amazon_' + filename[-1]
    return filename

### Main #############################################################################################
if __name__ == '__main__':
    if len(argv) < 2:
        print("Please provide filename to process")
    else:
        if argv[1].split('.')[-1] == 'csv':
            original_df = open_csv(argv[1])
            csv_name = make_csv_name(os.path.basename(argv[1]))
        elif argv[1].split('.')[-1] == 'gz':
            original_df = open_json(argv[1])
            csv_name = make_csv_name(os.path.basename(argv[1]))  
    ### compute the avg_self values
    avg_reviewers = original_df.groupby(['reviewerID']).mean().sort_values(['reviewerID'])
    avg_products = original_df.groupby(['asin']).mean().sort_values(['asin'])
    ### add the avg_others and stdev columns
    grouped_reviewers = group_and_transform(original_df, avg_products, 'reviewerID', 'asin')
    grouped_products = group_and_transform(original_df, avg_reviewers, 'asin', 'reviewerID')
    ### Bi-partition the reviewers and products by a 10000 index difference
    product_index = pd.Series(grouped_products.index)
    grouped_products = grouped_products.set_index(product_index + max(grouped_reviewers.index) + 10000).sort_index().reset_index().rename(columns={'index':'Node ID'})
    grouped_reviewers = grouped_reviewers.sort_index().reset_index().rename(columns={'index':'Node ID'})
    ### stack the reviewers and products into one users dataframe
    users_df = grouped_reviewers.append(grouped_products).astype({'Degree': int}).fillna(0)
    ### make the edges_df
    edges_df = merge_dfs(grouped_products, grouped_reviewers, original_df)
    print(edges_df)
    print(users_df)
    edges_df.to_csv(csv_name + '_edges2.csv', encoding = 'utf-8', index = False)
    print("Wrote edges csv")
    users_df.to_csv(csv_name + '_users.csv', encoding = 'utf-8', index = False)
    print("Wrote users csv")

