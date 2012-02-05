#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Author:
#     Mateusz Kruszyński <mateusz.kruszynski@gmail.com>

import sys, time, os.path, pickle
import pylab

from analysis.obci_signal_processing import read_manager
from analysis.csp import modCSPv2 as csp
from analysis.csp import signalParser as sp

from interfaces import interfaces_logging as logger
LOGGER = logger.get_logger("csp_analysis", 'info')

def run(in_file, out_file, use_channels, ignore_channels, montage, montage_channels):
    
	mgr = read_manager.ReadManager(
		in_file+'.obci.xml',
		in_file+'.obci.raw',
		in_file+'.obci.tag')
        to_frequency = int(float(mgr.get_param("sampling_frequency")))
	if use_channels is None:
		use_channels = mgr.get_param('channels_names')
	if ignore_channels is not None:
		for i in ignore_channels:
			try:
				use_channels.remove(i)
			except:
				pass

	exp_info = mgr.get_tags('experimentInfo')[0]['desc']
        to_signal = float(exp_info['target_time'])
        freqs = [int(i) for i in exp_info['all_freqs'].split(';')]
	dec_count = int(exp_info['fields_count'])


        data = sp.signalParser(in_file+'.obci')
        train_tags = data.get_train_tags(trial_separator_name='diodes', screen=True)
	LOGGER.info("Run csp with: use_channels: "+str(use_channels)+" motage: "+str(montage)+" montage_channels: "+str(montage_channels))
        q = csp.modCSP(in_file+'.obci', freqs, use_channels, montage, montage_channels)
	q.montage
        q.start_CSP(to_signal, to_frequency, baseline = False, filt='cheby', method = 'regular', train_tags = train_tags)#liczenie CSP
        time = pylab.linspace(1, to_signal, 7)
        t1, t2 = q.time_frequency_selection(to_frequency, train_tags, time=time, frequency_no=dec_count, plt=False)

        LOGGER.info("Got times t1: "+str(t1)+ " and t2: "+str(t2))
        value, mu, sigma, means, stds = q.count_stats(to_signal, to_frequency, train_tags, plt=True)#Liczenie statystyk
        LOGGER.info("For freqs: "+str(freqs))
        LOGGER.info("Got means: "+str(means))
        
        pairs = zip(means, freqs)
        pairs.sort(reverse=True)
        LOGGER.info("Sorted: "+str(pairs))
	best = [i[1] for i in pairs]
        LOGGER.info("Best freqs: "+str(best))
        
        LOGGER.info("Finished CSP with stats:")
        LOGGER.info(str(value) + " / " + str(mu) + " / " + str(sigma))
        LOGGER.info("And q:")
        LOGGER.info(str(q))
        
        csp_file = out_file+'.csp'
        f = open(csp_file, 'w')
        d = {'value': value,
             'mu': mu,
             'sigma': sigma,
             'q' : q,
	     'freqs':';'.join([str(i) for i in best[:dec_count]]),
	     'buffer':t2
             }
        pickle.dump(d, f)
        f.close()
