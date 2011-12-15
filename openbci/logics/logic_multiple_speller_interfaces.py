#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Author:
#     Mateusz Kruszyński <mateusz.kruszynski@gmail.com>
#
from ugm import ugm_config_manager
import os, time
import logic_logging as logger
LOGGER = logger.get_logger("logic_multiple_speller_interfaces", "info")

class SwitchInterface(object):
    def __init__(self, server):
        self._server = server
    def get_requested_configs(self):
        return ['MS_SWITCH_UGM',
                'MS_SWITCH_BLINK_MIN_BREAK',
                'MS_SWITCH_BLINK_MAX_BREAK',
                'MS_SWITCH_BLINK_DURATION'
                ]
    def set_configs(self, configs):
        self.configs = configs
        self._ugm_fields = str(ugm_config_manager.UgmConfigManager(configs['MS_SWITCH_UGM']).get_ugm_fields())

    def stop_speller(self):
        self._server.send_message({
                'type':'switch_control_message',
                'key':'stop',
                'value':''
                })
        self._server.send_message({
                'type':'ugm_control_message',
                'key':'stop_blinking',
                'value':''
                })
        
    def fire_speller(self):
        self._server.send_message({
                'type':'ugm_control_message',
                'key':'update_and_start_blinking',
                'value':''
                })
        self._server.send_message({
                'type':'switch_control_message',
                'key':'start',
                'value':''
                })

    def prepare_system(self):
        data = {
            'BLINK_ID_TYPE':'SEQUENTIAL',
            'BLINK_UGM_TYPE':'SINGLE',
            'BLINK_RUNNING_ON_START': "0",
            'BLINK_MIN_BREAK':self.configs['MS_SWITCH_BLINK_MIN_BREAK'],
            'BLINK_MAX_BREAK':self.configs['MS_SWITCH_BLINK_MAX_BREAK'],
            'BLINK_DURATION':self.configs['MS_SWITCH_BLINK_DURATION'],
            }
        
        for k, v in data.iteritems():
            self._server.send_message({
                    'type':'dict_set_message',
                    'key':k,
                    'value':v,
                    })

        self._server.send_message({
                'type':'ugm_update_message',
                'update_type':0,
                'value':self._ugm_fields
                })

    def get_instruction(self):
        return u'Dupa dupa \nbla  bla'






class EtrClassic(object):
    def __init__(self, server):
        self._server = server

    def get_requested_configs(self):
        return ['MS_ETR_CLASSIC_UGM']
    def set_configs(self, configs):
        self.configs = configs
        self._ugm_fields = str(ugm_config_manager.UgmConfigManager(configs['MS_ETR_CLASSIC_UGM']).get_ugm_fields())
    def stop_speller(self):
        self._server.send_message({
                'type':'etr_control_message',
                'key':'stop',
                'value':''
                })
        
    def fire_speller(self):
        self._server.send_message({
                'type':'etr_control_message',
                'key':'start',
                'value':''
                })

    def prepare_system(self):
        self._server.send_message({
                'type':'ugm_update_message',
                'update_type':0,
                'value':self._ugm_fields
                })

    def get_instruction(self):
        return u'Dupa dupa \nbla  bla - etr'






class Ssvep(object):
    def __init__(self, server):
        self._server = server

    def get_requested_configs(self):
        return ['MS_SSVEP_UGM']

    def set_configs(self, configs):
        self.configs = configs
        self._ugm_fields = str(ugm_config_manager.UgmConfigManager(configs['MS_SSVEP_UGM']).get_ugm_fields())

    def stop_speller(self):
        self._server.send_message({
                'type':'ssvep_control_message',
                'key':'stop',
                'value':''
                })
        
    def fire_speller(self):
        self._server.send_message({
                'type':'ssvep_control_message',
                'key':'start',
                'value':''
                })

    def prepare_system(self):
        self._server.send_message({
                'type':'ugm_update_message',
                'update_type':0,
                'value':self._ugm_fields
                })

    def get_instruction(self):
        return u'Dupa dupa \nbla  bla - ssvep'
