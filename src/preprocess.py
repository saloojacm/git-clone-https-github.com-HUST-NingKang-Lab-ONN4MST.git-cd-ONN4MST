#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import argparse

des = '''
This is an integrated data preprocessor for Ontology-aware Neural Network.

Work mode:
\tcheck mode: check all of your data files, the error data file are saved in tmp/ folder.
\tbuild mode: de novoly build a species tree using your own data (deprecated).
\tconvert mode: convert tsv file from EBI MGnify database to model acceptable n-dimensional array.
\tfilter mode: filter features. get npz with selected features from npz with all features.
\tcount mode: count the number of samples in each biome (deprecated).
\tmerge mode: merge multiple npz files to a single npz.
\tselect mode: do feature selection for merged matrices npz (deprecated).
'''
parser = argparse.ArgumentParser(description=des, formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument("mode", type=str, choices=['check', 'build', 'convert', 'filter', 'count', 'merge', 'select'],
					default='',
					help="Work mode of the program. default: None")
parser.add_argument("-p", "--n_jobs", type=int, default=1,
					help='The number of processors to use. default: 1')
parser.add_argument("-b", "--batch_index", type=int, default=-1,
					help='The batch number to process, -1 means process all at once. default: -1')
parser.add_argument("-s", "--batch_size", type=int, default=1000,
					help='The number of samples in each batch. -1 means process all at once. default: -1')
parser.add_argument("-i", '--input_dir', type=str, default='data/tsvs/',
					help='Input directory, must be parent folder of biome folders. default: data/tsvs')
parser.add_argument("-o", '--output_dir', type=str, default='data/npzs/',
					help='Output directory. default: data/npzs')
parser.add_argument("-t", '--tree', type=str, default='data/trees/',
					help='The directory of trees (species_tree.pkl and biome_tree.pkl). default: data/tree/')
parser.add_argument("-c", '--coef', type=float, default=1e-3,
					help='The coefficient for determining threshold when selecting features. default: 1e-3')
parser.add_argument('--header', type=int, default=1,
					help='The number of header in tsv files. default: 1')

args = parser.parse_args()

if args.mode in ['check', 'build', 'convert', 'filter', 'count', 'merge', 'select']:
	import gc
	import os
	import pickle
	import numpy as np
	import pandas as pd
	from tqdm import tqdm, trange
	from joblib import Parallel, delayed
	from dp_utils import DataLoader, IdConverter, Selector, npz_merge
	from functools import reduce
	from livingTree import SuperTree
else:
	print('Must specify a valid work mode, type -h to get the help information.')

# Global settings
if args.mode == 'convert':
	loader = DataLoader(path=args.input_dir, batch_size=args.batch_size, batch_index=args.batch_index)
elif args.mode in ['check', 'build', 'count']:
	loader = DataLoader(path=args.input_dir)
else:
	pass

if not os.path.isdir(args.output_dir):
	os.mkdir(args.output_dir)

if not os.path.isdir(args.tree):
	os.mkdir(args.tree)


def convert_to_npzs(sample, biome_layered, matrix_ncol,
					species_tree, st_bottom_up_ids, paths_to_gen_matrix, biome_tree):
	species_tree = pickle.loads(pickle.dumps(species_tree))
	biome_tree = pickle.loads(pickle.dumps(biome_tree))
	# Map abundance
	species_tree.fill_with(data=sample)
	# Recalculate abundance
	species_tree.update_values(bottom_up_ids=st_bottom_up_ids)
	Sum = species_tree['root'].data
	# Calculate relative abundance
	matrix = np.divide(species_tree.get_matrix(paths=paths_to_gen_matrix, ncol=matrix_ncol), Sum).astype(np.float32)  
	# Generate labels for sample
	biome_tree.fill_with(data={biome: 1 for biome in biome_layered})
	bfs_data = biome_tree.get_bfs_data()
	labels = [np.array(bfs_data[level], dtype=np.float32) for level in range(1, biome_tree.depth() + 1)]
	
	# Recycle memory
	del matrix_ncol
	del Sum
	del species_tree 
	del biome_tree 
	del bfs_data 
	del paths_to_gen_matrix 
	del st_bottom_up_ids 
	del sample 
	del biome_layered
	gc.collect()

	return matrix, labels

if args.mode == 'check':
	# tested
	# Check files, save error file list and error massages
	loader.check_data(header=args.header)
	loader.save_error_list()

elif args.mode == 'build':
	# tested
	# Construct the phylogenetic tree and biome tree, deprecated.
	converter = IdConverter()
	paths = pd.concat(map(lambda x: x.iloc(1)[2], tqdm(loader.get_data(header=args.header))))
	# Drop repeated paths
	paths = paths.unique()
	paths = [converter.fix_issue2_3(path) for path in paths]
	paths = [converter.convert(x, sep=';') for x in paths]
	stree = SuperTree()
	stree.create_node(identifier='root')
	print('Building tree', flush=True)
	stree.from_paths(tqdm(paths))
	# Dump the phylogenetic tree
	stree.to_pickle(file=os.path.join(args.tree, 'species_tree.pkl'))

	# Fix issue 1
	biomes_fixed = [x.replace('Host-associated', 'Host_associated').\
					   replace('Oil-contaminated', 'Oil_contaminated').\
					   replace('Non-marine', 'Non_marine') for x in os.listdir(args.input_dir)]

	biomes = map(lambda x: converter.convert(x, sep='-'), biomes_fixed)
	biomes = list(map(lambda x: x[1:], biomes))
	# print(biomes)
	btree = SuperTree()
	btree.create_node(identifier='root')
	btree.from_paths(biomes)
	# Dump the biome tree
	btree.to_pickle(file=os.path.join(args.tree, 'biome_tree.pkl'))
	print('Species tree and biome tree are saved in {}'.format(args.tree))
	# Save basic informations of biome tree.
	ordered_labels = ['\nlayer_'+str(nlayer)+'\n'+'\n'.join(labels) for nlayer, labels in enumerate(btree.get_bfs_nodes().values())]
	with open(os.path.join(args.tree, 'ordered_labels.txt'), 'w') as f:
		f.write('\n'.join(ordered_labels))
	print('Ordered_labels are saved in',os.path.join(args.tree, 'ordered_labels.txt'))
	ids = btree.get_top_down_ids()
	restore = lambda x: x.replace('Host_associated', 'Host-associated').\
		replace('Oil_contaminated', 'Oil-contaminated').replace('Non_marine', 'Non-marine')
	biomes_split = pd.DataFrame()
	biomes_split['ONN Microbiome'] = ids
	biomes_split['EBI Microbiome'] = biomes_split['ONN Microbiome'].apply(lambda x: restore(x.split('-')[-1]))
	biomes_split = biomes_split.sort_values(by='EBI Microbiome', axis=0)
	biomes_split = biomes_split[['EBI Microbiome','ONN Microbiome']]
	biomes_split.to_csv(os.path.join(args.tree, 'EBI_ONN_Microbiome.tsv'), sep='\t', index=False)
	biomes_split.to_excel(os.path.join(args.tree, 'EBI_ONN_Microbiome.xls'), index=False)
	print('Microbiome in EBI&ONN format are saved in {} and {}'.format(os.path.join(args.tree,
																					  'EBI_ONN_Microbiome.tsv'),
																		 os.path.join(args.tree,
																					  'EBI_ONN_Microbiome.xls')))

elif args.mode == 'convert':
	# Convert input data into model-acceptable npz files

	# Read trees
	print('Loading trees......', end='', flush=True)
	tree = SuperTree()
	converter = IdConverter()
	stree = tree.from_pickle(os.path.join(args.tree, 'species_tree.pkl'))
	stree.init_nodes_data(value=0)  # put this outside
	btree = tree.from_pickle(os.path.join(args.tree, 'biome_tree.pkl'))
	btree.init_nodes_data(value=0)  # put this outside
	print('finished !')
	print('Preprocessing data......', end='', flush=True)
	raw_data = [x.iloc(1)[1:] for x in tqdm(loader.get_data(header=args.header))]
	fix = converter.fix_issue2_3

	# Find nearest node on the tree.
	def nearest_node_onTree(stree, path):
		res = 'root'
		#print(path)
		for id_ in reversed(path):
			if stree.contains(id_):
				res = id_
				break
		return res
	nnt = nearest_node_onTree

	# Preprocess the dataframe.
	def format_df(stree, df):
		colnames = df.columns
		df = df.rename(columns={colnames[0]: 'abundance', colnames[1]: 'taxonomy'})
		df['path'] = df['taxonomy'].apply(lambda x: converter.convert(fix(x.lstrip('Root;') if x.startswith('Root;') else x), sep=';'))
		df['nearest id'] = df['path'].apply(lambda x: nnt(stree, x))
		ndf = pd.DataFrame()
		ndf['nearest id'] = pd.unique(df['nearest id'])#									  'abundance'
		#print(df.columns)
		ndf['abundance in total'] = ndf['nearest id'].apply(lambda x: df[df['nearest id']==x]['abundance'].sum())
		ndf = ndf[['nearest id', 'abundance in total']]
		return {nid: abun for nid, abun in ndf.values.tolist()}
	data = [format_df(stree, df) for df in tqdm(raw_data)]
	# fix issue 1
	biomes_fixed = [x.replace('Host-associated', 'Host_associated').\
					   replace('Oil-contaminated', 'Oil_contaminated').\
					   replace('Non-marine', 'Non_marine') for x in loader.paths_keep]

	pth_split = os.path.split
	biomes = [converter.convert(pth_split(pth_split(x)[0])[-1], sep='-') for x in biomes_fixed]
	print('finished !')
	print('Total: {} biomes and {} samples'.format(len(biomes), len(data)))

	# Back up the parameters during the first calculation, 
	# no need to repeatedly calculate in the future
	if 'prep_conf.pkl' in os.listdir('config'):
		print('Found a backup and recovering parameters from it.......', end='')
		with open('config/prep_conf.pkl', 'rb') as f:
			conf = pickle.load(f)
		st_bottom_up_ids = conf['st_bottom_up_ids']
		st_ids_by_level = conf['st_ids_by_level']
		paths_to_gen_matrix = conf['paths_to_gen_matrix']
		matrix_ncol = conf['matrix_ncol']
		print('finished !')
	else:
		print('No backup found, calculating parameters that do not change during iteration......', end='')
		st_bottom_up_ids = stree.get_bottom_up_ids()
		st_ids_by_level = stree.get_ids_by_level()
		paths_to_gen_matrix = stree.get_paths_to_level(ids_by_level=st_ids_by_level, level=7,
												   include_inner_leaves=True)
		paths_to_gen_matrix = [path[1:] for path in paths_to_gen_matrix]
		print('paths:')
		print(paths_to_gen_matrix[0:10])
		matrix_ncol = max([len(path) for path in paths_to_gen_matrix])
		params = {'st_bottom_up_ids': st_bottom_up_ids, 'st_ids_by_level': st_ids_by_level, 
				  'paths_to_gen_matrix': paths_to_gen_matrix, 'matrix_ncol': matrix_ncol}
		print('finished !\nBacking up parameters to config/preprocessing.pkl', end='')
		with open('config/prep_conf.pkl', 'wb') as f:
			pickle.dump(params, f)
		# how about fixing k_bact with sk_bact
		print('finished !')

	# Define convert function
	# Pre-compute reverse iteration node id order
	# Pre-generate paths to node ids
	par_backend = 'threads' # {???processes???, ???threads???}
	print('Using joblib `{}` parallel backend with {} cores'.format(par_backend, args.n_jobs))
	par = Parallel(n_jobs=args.n_jobs, prefer=par_backend)
	# Perform conversion.
	print('Performing conversion......')
	res = par(delayed(convert_to_npzs)(sample=data[i], biome_layered=biomes[i], matrix_ncol=matrix_ncol,
									   species_tree=stree, st_bottom_up_ids=st_bottom_up_ids,
									   paths_to_gen_matrix=paths_to_gen_matrix, biome_tree=btree)
			  for i in trange(len(data))
			  )
	
	# Post-process and save result.
	raw_npzs = list(zip(*res))
	matrices = raw_npzs[0]
	labels = raw_npzs[1]
	labels = [[np.array(label[i]) for label in labels] for i in range(len(labels[0]))]
	# save
	output_dir = os.path.join(args.output_dir, 'batch_'+str(args.batch_index)+'.npz')
	np.savez(output_dir, matrices=matrices, label_0=labels[0], label_1=labels[1],
			 label_2=labels[2], label_3=labels[3], label_4=labels[4])
	with open(os.path.join(args.output_dir+'/batch_')+str(args.batch_index)+'.txt', 'w') as f:
		f.write('\n'.join(biomes_fixed))
	print('Results are save in {}.'.format(output_dir))

elif args.mode == 'filter':
	# Get npz fils based on selected features.
	npzs = [os.path.join(args.input_dir, npz) for npz in os.listdir(args.input_dir) if npz.endswith('.npz')]
	# Read configurations
	indices = np.load('tmp/1462FeatureIndices.npz')
	abu_indices = indices['abu_select']
	imptc_indices = indices['imptc_select']
	print(list(indices.keys()))

	filter_features = lambda matrices: matrices[:, abu_indices, :][:, imptc_indices, :]
	print('processing...')
	# Get matrices based on selected features.
	for npz in tqdm(npzs):
		f = np.load(npz)
		matrices = filter_features(f['matrices'])
		np.savez(os.path.join(args.output_dir, 'selected_' + npz.split('/')[-1]), matrices=matrices, label_0=f['label_0'],
				 label_1=f['label_1'], label_2=f['label_2'], label_3=f['label_3'], label_4=f['label_4'])

elif args.mode == 'count':
	# tested
	# Deprecated
	sample_count = loader.get_sample_count()
	res = pd.DataFrame(list(sample_count.items()), columns=['Microbiome', 'Sample size'])

	print('Generating ONN format result...')
	fix_issue_1 = lambda x: x.replace('Host-associated', 'Host_associated').\
		replace('Oil-contaminated', 'Oil_contaminated').\
		replace('Non-marine', 'Non_marine')
	res['Microbiome'] = res['Microbiome'].apply(lambda x: fix_issue_1(os.path.split(x)[1]))
	# id conversion needed
	res.to_excel(os.path.join(args.output_dir, 'sample_count_ONN_format.xls'), index=False)
	res.to_csv(os.path.join(args.output_dir, 'sample_count_ONN_format.tsv'), sep='\t', index=False)
	print('Finished !')
	print('Generating EBI format result...')
	restore = lambda x: x.replace('Host_associated', 'Host-associated').\
		replace('Oil_contaminated', 'Oil-contaminated').replace('Non_marine', 'Non-marine')
	res['Microbiome'] = res['Microbiome'].apply(lambda x: x.replace('-', ' > ')).apply(restore)
	res.to_excel(os.path.join(args.output_dir, 'sample_count_EBI_format.xls'), index=False)
	res.to_csv(os.path.join(args.output_dir, 'sample_count_EBI_format.tsv'), sep='\t', index=False)
	print('Finished !')
	print('Generating DLMER format result...')
	text_res = ['{}:{}'.format(fix_issue_1(biome), count) for biome, count in sample_count.items()]
	with open(os.path.join(args.output_dir, 'sample_count_DLMER_format.txt'), 'w') as f:
		f.write('\n'.join(text_res))
	print('Finished !')
	print('Results are saved in {}'.format(args.output_dir))

elif args.mode == 'merge':
	# tested
	# Merge multiple npz files into a single npz
	files = [x for x in os.listdir(args.input_dir) if x.endswith('.npz')]
	files.sort(key=lambda x: int(x.lstrip('batch_').rstrip('.npz')))
	print(files)
	files = map(lambda x: os.path.join(args.input_dir, x), files)
	merged_npz = npz_merge(files)
	np.savez(os.path.join(args.output_dir, 'merged_matrices.npz'),
			 matrices=merged_npz['matrices'],
			 label_0=merged_npz['label_0'],
			 label_1=merged_npz['label_1'],
			 label_2=merged_npz['label_2'],
			 label_3=merged_npz['label_3'],
			 label_4=merged_npz['label_4'])

elif args.mode == 'select':
	# tested
	# Deprecated
	coefficient = args.coef
	print('Loading data...')
	tmp = np.load(os.path.join(args.input_dir, 'merged_matrices.npz'))
	matrices = tmp['matrices']
	print('Finished !')
	print('Matrices shape now: {}'.format(matrices.shape))
	print('Concatenating labels...')
	labels_ = {i: tmp[i] for i in ['label_0', 'label_1', 'label_2', 'label_3', 'label_4']}
	labels = reduce(lambda x, y: np.concatenate((x, y), axis=1), labels_.values())
	print('Finished !')
	selector = Selector(matrices)
	print('Performing basic feature selection...')
	selector.run_basic_select(coefficient=coefficient)
	feature_ixs = selector.basic_select__
	tmp_matrices = matrices[:, feature_ixs, :]
	print('Finished !')
	print('Matrices shape after basic selecting: {}'.format(tmp_matrices.shape))

	indeces_backup = selector.basic_select__

	print('Performing random forest regression feature selection...')
	selector = Selector(tmp_matrices)
	selector.cal_feature_importance(label=labels, n_jobs=args.n_jobs)
	selector.run_RF_regression_select(coefficient=coefficient)
	feature_ixs = selector.RF_select__
	new_matrices = tmp_matrices[:, feature_ixs, :]
	print('Finished !')
	print('Matrices shape after random forest regression selecting: {}'.format(new_matrices.shape))
	out_name = 'matrices_{}_features_coef_{}.npz'.format(new_matrices.shape[1], args.coef)
	np.savez(os.path.join(args.output_dir, out_name),
			 matrices=new_matrices,
			 label_0=labels_['label_0'],
			 label_1=labels_['label_1'],
			 label_2=labels_['label_2'],
			 label_3=labels_['label_3'],
			 label_4=labels_['label_4'])
	print('Result are saved in {}'.format(os.path.join(args.output_dir, out_name)))
	conf_name = 'indeces_for_{}features_{}C.npz'.format(new_matrices.shape[1], args.coef)
	np.savez('tmp/'+conf_name, abu_select=indeces_backup, imptc_select=selector.RF_select__)
	print('The indeces of selected features are saved in tmp/{}'.format(conf_name))




