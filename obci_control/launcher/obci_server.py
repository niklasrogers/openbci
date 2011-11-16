#!/usr/bin/python
# -*- coding: utf-8 -*-

import subprocess
import uuid
import argparse
import os.path
import sys
import json
import time

import zmq

from common.message import OBCIMessageTool, send_msg, recv_msg
from launcher_messages import message_templates, error_codes

from obci_control_peer import OBCIControlPeer, basic_arg_parser
import common.obci_control_settings as settings

import obci_experiment
import obci_process_supervisor

class OBCIServer(OBCIControlPeer):
	def __init__(self, obci_install_dir, other_srv_addresses,
												rep_addresses=None,
												pub_addresses=None,
												name='obci_server'):
		self.other_addrs = other_srv_addresses
		self.experiments = {}
		self.exp_processes = {}

		self.__all_sockets = []

		super(OBCIServer, self).__init__(obci_install_dir, None, rep_addresses,
														  pub_addresses,
														  name)
		#TODO do sth with other server rep addresses

	def net_init(self):
		super(OBCIServer, self).net_init()



	def pre_run(self):
		"""
		Subclassed from OBCIControlPeer. Create a file in temp directory with
		REP addresses.
		"""
		directory = os.path.abspath(settings.DEFAULT_SANDBOX_DIR)
		if not os.path.exists(directory):
			os.mkdir(directory)

		filename = settings.SERVER_CONTACT_NAME
		self.fpath = os.path.join(directory, filename)
		if os.path.exists(self.fpath):
			print "\nOBCIServer contact file exists, \
probably a server is already working"
			print "Abort.\n"
			sys.exit(2)

		with open(self.fpath, 'w') as f:
			json.dump(self.rep_addresses, f)


	def clean_up(self):
		os.remove(self.fpath)


	def start_experiment(self, sandbox_dir, launch_file):
		path = obci_experiment.__file__
		path = '.'.join([path.rsplit('.', 1)[0], 'py'])

		exp = subprocess.Popen([path, '--srv-addresses', str(self.addresses),
										'--obci-dir', self.obci_install_dir,
										'--sandbox-dir', str(sandbox_dir),
										'--launch-file', str(launch_file),
										'--name', str(launch_file).split('.')[0]
										])
		return exp


	def handle_register_supervisor(self, message, sock):
		sv_uuid = message["uuid"]
		new_sv = self.supervisors[sv_uuid] = {}
		new_sv["rep_addrs"] = message["rep_addrs"]
		new_sv["pub_addrs"] = message["pub_addrs"]
		new_sv["name"] = message["name"]

		result = self.mtool.fill_msg("rq_ok")
		if message["main"]:
			if self.main_sv == None:
				self.main_sv = uuid
			else:
				result = self.mtool.fill_msg("rq_error",
					request=message, err_code="main_supervisor_already_exists")
		send_msg(sock, result)

	def handle_register_experiment(self, message, sock):
		send_msg(sock, self.mtool.fill_msg("rq_ok"))

	def handle_register_peer(self, message, sock):
		if message["peer_type"] == "obci_client":
			send_msg(sock, self.mtool.fill_msg("rq_ok"))
		else:
			super(OBCIServer, self).handle_register_peer(message_sock)

	def handle_create_experiment(self, message, sock):
		launch_file = message["launch_file"]
		sandbox = message["sandbox_dir"]
		sandbox = sandbox if sandbox else settings.DEFAULT_SANDBOX_DIR
		exp = self.start_experiment(sandbox, launch_file)

		self.exp_processes[exp_pid] = exp
		#TODO this is ugly
		time.sleep(0.0001)
		if exp.poll() is None:
			send_msg(sock, self.mtool.fill_msg("rq_ok"))



def server_arg_parser(add_help=False):
	parser = argparse.ArgumentParser(parents=[basic_arg_parser()],
							description="OBCI Server : manage OBCI experiments.",
							add_help=add_help)
	parser.add_argument('--other-srv-addresses', nargs='+',
	                   help='REP Addresses of OBCI servers on other machines')
	parser.add_argument('--name', default='obci_server',
	                   help='Human readable name of this process')
	return parser


if __name__ == '__main__':
	parser = server_arg_parser(add_help=True)

	args = parser.parse_args()

	srv = OBCIServer(args.obci_dir, args.other_srv_addresses,
							args.rep_addresses, args.pub_addresses, args.name)
	srv.run()