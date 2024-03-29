#!/usr/bin/env python
# -*- coding: utf-8 -*-

import random, time
import numpy as np

from obci.interfaces.bci.p300_fda.p300_fda import P300_analysis
from obci.interfaces.bci.p300_fda.p300_draw import P300_draw
from signalAnalysis import DataAnalysis
from obci.utils import context as ctx

DEBUG = False

class BCIP300FdaAnalysis(object):
    def __init__(self, send_func, cfg, montage_matrix, sampling, dec_count,
                 context=ctx.get_dummy_context('BCIP300FdaAnalysis')):
        self.logger = context['logger']
        self.send_func = send_func
        self.last_time = time.time()
        self.fs = sampling
        self.montage_matrix = montage_matrix
        use_channels = cfg['use_channels']

        self.nPole = np.zeros( dec_count)
        self.nMin = cfg['nMin']
        self.nMax = cfg['nMax']

        # For plotting purpose
        csp_time = cfg['csp_time']
        
        # For analysis purpose
        self.csp_time = np.array(csp_time)*self.fs
        
        avrM = cfg['avrM']
        conN = cfg['conN']
        
        print "cfg['w']: ", cfg['w']
        self.p300 = P300_analysis(sampling, cfg, fields= dec_count)
        self.p300.setPWC( cfg['P'], cfg['w'], cfg['c'])
        
        self.debugFlag = cfg['debug_flag']
        
        if self.debugFlag:
            self.p300_draw = P300_draw(self.fs)
            self.p300_draw.setTimeLine(conN, avrM, csp_time)
        
        self.epochNo = 0
        
        

    def analyse(self, blink, data):
        """Fired as often as defined in hashtable configuration:
        # Define from which moment in time (ago) we want to get samples (in seconds)
        'ANALYSIS_BUFFER_FROM':
        # Define how many samples we wish to analyse every tick (in seconds)
        'ANALYSIS_BUFFER_COUNT':
        # Define a tick duration (in seconds).
        'ANALYSIS_BUFFER_EVERY':
        # To SUMP UP - above default values (0.5, 0.4, 0.25) define that
        # every 0.25s we will get buffer of length 0.4s starting from a sample 
        # that we got 0.5s ago.
        # Some more typical example would be for values (0.5, 0.5 0.25). 
        # In that case, every 0.25 we would get buffer of samples from 0.5s ago till now.

        data format is determined by another hashtable configuration:
        # possible values are: 'PROTOBUF_SAMPLES', 'NUMPY_CHANNELS'
        # it indicates format of buffered data returned to analysis
        # NUMPY_CHANNELS is a numpy 2D array with data divided by channels
        # PROTOBUF_SAMPLES is a list of protobuf Sample() objects
        'ANALYSIS_BUFFER_RET_FORMAT'

        """
        self.logger.debug("Got data to analyse... after: "+str(time.time()-self.last_time))
        self.logger.debug("first and last value: "+str(data[0][0])+" - "+str(data[0][-1]))
        self.last_time = time.time()
        
        # Get's montaged signal
        signal = np.dot(self.montage_matrix.T, data)
        signal = signal[:,self.csp_time[0]:self.csp_time[1]]

        # Counts each blink
        self.nPole[blink.index] += 1

        # Classify each signal
        self.p300.testData(signal, blink.index)
        dec = -1

        # If statistical significanse
        if self.p300.isItEnought() != -1:
            dec = self.p300.getDecision()

        #~ if (dec == -1) and (self.nPole.min() >= self.nMax):
            #~ dec = self.p300.forceDecision()

        print "dec: ", dec

        if dec != -1:
            self.logger.info("Decision from P300: " +str(dec) )
            
            if self.debugFlag:
                self.p300_draw.savePlotsSignal(self.p300.getSignal(), 'signal_%i_%i.png' %(self.epochNo,dec) )
                #~ self.p300_draw.savePlotsD(self.p300.getArrTotalD(), self.pVal, 'dVal_%i_%i.png' %(self.epochNo,dec))
            
            self.p300.newEpoch()
            self.epochNo += 1
            
            self.nPole = np.zeros( self.nPole.shape)
            
            self.send_func(dec)
        else:
            self.logger.info("Got -1 ind- no decision")
