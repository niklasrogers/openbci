#!/usr/bin/env python
# -*- coding: utf-8 -*-

#####
# To have:
# class squares:
#    count - returns number of squares
#    



from multiplexer.multiplexer_constants import peers, types
from obci.control.peer.configured_multiplexer_server import ConfiguredMultiplexerServer
from obci.configs import settings, variables_pb2
import random, time, sys

from obci.interfaces import interfaces_logging as logger

import numpy as np

LOGGER = logger.get_logger("etr_analysis", "info")


class EtrAnalysis(ConfiguredMultiplexerServer):
    def __init__(self, addresses):
        super(EtrAnalysis, self).__init__(addresses=addresses,
                                     type=peers.ETR_P300_ANALYSIS)
                                     
        self.initConstants()
        self.ready()

    def initConstants(self):
        """
        Initiates constants values.
        """
        
        bufforLen = 10

        self.buffor = np.zeros((2,bufforLen))
        self.metricBuffor = np.zeros((square.count, bufforLen))

    def metric(self, xy):
        """
        Measures metric in squares space.
        """

        # For each square calc distance from present xy
        for i, s in enumaret(square.count):
            m[i] = np.sqrt(np.dot(xy,s.xy))
            
        return m

    def _update_heatmap(self, m):
        """
        Updates values of heatmap and creates probabilty 
        density for each epoch.
        """
        
        self.metricBuffor = np.concatenate( (self.metricBuffor, m), axis=1)[:,1:]
    
    def calc_pdf(self):
        self.pdf = np.sum(self.metricBuffor, axis=1)
        self.pdf = self.pdf/np.sum(self.pdf)
        return self.pdf
    
    def _update_buffor(self, xy):
        """
        Updates buffor of gaze values.
        """
        self.buffor = np.concatenate( (self.buffor, xy), axis=1)[:,1:]
    
    def handle_message(self, mxmsg):
        LOGGER.info("EtrAnalysis\n")
        if mxmsg.type == types.ETR_CALIBRATION_RESULTS:
            res = variables_pb2.Sample()
            res.ParseFromString(mxmsg.message)
            LOGGER.debug("GOT ETR CALIBRATION RESULTS: "+str(res.channels))
            #zrob cos z macierza kalibracji

        elif mxmsg.type == types.ETR_SIGNAL_MESSAGE:
            l_msg = variables_pb2.Sample2D()
            l_msg.ParseFromString(mxmsg.message)
            LOGGER.debug("GOT MESSAGE: "+str(l_msg))
            
            
            
            # Change shape of data  
            x, y = l_msg.x, l_msg.y
            xy = np.array([[x],[y]])
            
            self._update_buffor(xy)
            
            # Caunt metric
            m = self.metric(xy)
            self._update_heatmap(m)
            
            # Calc heatmap as probabilty density
            pdf = self.calc_probDensity()
            
            ##self.conn.send_message(message = str(dec), type = types.DECISION_MESSAGE, flush=True)
            l_msg.ParseFromString(mxmsg.message)
            LOGGER.debug("GOT MESSAGE: "+str(l_msg))
            #zrob cos z sygnalem

        elif mxmsg.type == types.BLINK_MESSAGE:
            blink = variables_pb2.Blink()
            blink.ParseFromString(mxmsg.message)
            LOGGER.debug("GOT BLINK: "+str(blink.index)+" / "+str(blink.timestamp))
            #zrob cos z blinkiem

        self.no_response()

    def _send_results(self):
        r = variables_pb2.Sample()
        t.timestamp = time.time()
        for i in range(8):
            r.channels.append(random.random())
        self.conn.send_message(message = r.SerializeToString(), type = types.ETR_ANALYSIS_RESULTS, flush=True)


if __name__ == "__main__":
    EtrAnalysis(settings.MULTIPLEXER_ADDRESSES).loop()

