#!/usr/bin/python
# -*- coding: utf-8 -*-

import threading
import subprocess
import sys
import os
import time
import socket
import signal

import zmq

from common.message import OBCIMessageTool, PollingObject, send_msg, recv_msg
from launcher_messages import message_templates

from utils.openbci_logging import get_logger

from process_io_handler import ProcessIOHandler, DEFAULT_TAIL_RQ

PING = 2
RETURNCODE = 4

MONITORING_OPTIONS = [PING, RETURNCODE]

NO_STDIO = 0
STDOUT = 1
STDERR = 2
STDIN = 4

STDIO = [NO_STDIO, STDOUT, STDERR, STDIN]

PYTHON_CALL = ['python']#, '-u']

REGISTER_TIMEOUT = 3

_DEFAULT_TIMEOUT = 20
_DEFAULT_TIMEOUT_MS = 6000


class SubprocessMonitor(object):
    def __init__(self, zmq_ctx, uuid, logger=None):
        self._processes = {}
        self._ctx = zmq_ctx
        self.uuid = uuid
        self.logger = logger or get_logger('subprocess_monitor',
                                stream_level='warning')

        self._mtool = OBCIMessageTool(message_templates)
        self.poller = PollingObject()
        self._proc_lock = threading.RLock()

    def not_running_processes(self):
        status = {}
        with self._proc_lock:
            for key, proc in self._processes.iteritems():
                st = proc.status()
                if st[0] in [FINISHED, FAILED, TERMINATED] and not proc.marked_delete():
                    status[key] = st

        return status

    def unknown_status_processes(self):
        with self._proc_lock:
            return [proc for proc in self._processes.values()\
                            if proc.status()[0] == UNKNOWN]

    def process(self, machine_ip, pid):
        with self._proc_lock:
            return self._processes.get((machine_ip, pid), None)

    def killall(self, force=False):
        with self._proc_lock:
            for proc in self._processes.values():
                kill_method = proc.kill if not force else proc.kill_with_force
                if proc.status()[0] not in [FINISHED, FAILED, TERMINATED]:
                    kill_method()
                    #proc.kill()
                #del proc

    def delete_all(self):
        with self._proc_lock:
            for proc in self._processes.values():
                del proc
            self._processes = {}

    def stop_monitoring(self):
        with self._proc_lock:
            for proc in self._processes.values():
                proc.stop_monitoring()

    def new_local_process(self, path, args, proc_type='', name='',
                                capture_io= STDOUT | STDIN,
                                stdout_log=None,
                                stderr_log=None,
                                register_timeout_desc=None,
                                monitoring_optflags=RETURNCODE | PING,
                                machine_ip=None,
                                env=None):

        if path.endswith('.py'):
            launch_args = PYTHON_CALL +[path] + args
        else:
            launch_args = [path] + args
        self.logger.info(proc_type + " local path:  " + path)
        machine = machine_ip if machine_ip else socket.gethostname()

        out = subprocess.PIPE if capture_io & STDOUT else None

        if capture_io & STDERR:
            err = subprocess.PIPE
        elif out is not None:
            err = subprocess.STDOUT
        else: err = None

        stdin = subprocess.PIPE if capture_io & STDIN else None


        timeout_desc = register_timeout_desc

        ON_POSIX = 'posix' in sys.builtin_module_names
        
        try:
            popen_obj = subprocess.Popen(launch_args,
                                        stdout=out, stderr=err, stdin=stdin,
                                        bufsize=1, close_fds=ON_POSIX, env=env)
        except OSError as e:
            details = "{0} : Unable to spawn process {1} [{2}]".format(
                                                        machine, path, e.args)
            self.logger.error(details)
            return None, details
        except ValueError as e:
            details = "{0} : Unable to spawn process (bad arguments) \
{1} [{2}]".format(machine, path, e.args)
            self.logger.error(details)
            return None, details
        except Exception as e:
            return None, "Error: " + str(e) + str(e.args)
        else:
            if popen_obj.returncode is not None:
                self.logger.warning("opened process already terminated"
                                        + popen_obj.communicate())
            if not name:
                name = os.path.basename(path)
            process_desc = ProcessDescription(proc_type=proc_type,
                                            name=name,
                                            path=path,
                                            args=args,
                                            machine_ip=machine,
                                            pid=popen_obj.pid)

            io_handler = None
            if out is not None or err is not None or stdin is not None:

                out_handle = popen_obj.stdout if out is not None else None
                if err == subprocess.STDOUT or err is None:
                    err_handle = None
                else: err_handle = popen_obj.stderr

                in_handle = popen_obj.stdin if stdin is not None else None

                io_handler = ProcessIOHandler(
                                name=':'.join([machine, path, name]),
                                stdout=out_handle,
                                stderr=err_handle,
                                stdin=in_handle,
                                out_log=stdout_log, err_log=stderr_log)
                io_handler.start_output_handler()

            new_proc = LocalProcess(process_desc, popen_obj, io_handler=io_handler,
                                reg_timeout_desc=timeout_desc,
                                monitoring_optflags=monitoring_optflags,
                                logger=self.logger)

            if monitoring_optflags & PING:
                new_proc._ctx = self._ctx

            with self._proc_lock:
                self._processes[(machine, popen_obj.pid)] = new_proc

            new_proc.start_monitoring()

            return new_proc, None



    def new_remote_process(self, path, args, proc_type, name,
                                machine_ip, conn_addr,
                                capture_io= STDOUT | STDIN,
                                stdout_log=None,
                                stderr_log=None,
                                register_timeout_desc=None,
                                monitoring_optflags=PING):
        """Send a request to conn_addr for a process launch. By default
        the process will be monitored with ping requests and locally by the
        remote peer."""


        timeout_desc = register_timeout_desc

        rq_message = self._mtool.fill_msg('launch_process',
                                path=path,
                                args=args, proc_type=proc_type,
                                name=name,
                                machine_ip=machine_ip,
                                capture_io=capture_io,
                                stdout_log=stdout_log,
                                stderr_log=stderr_log)

        rq_sock = self._ctx.socket(zmq.REQ)

        try:
            rq_sock.connect(conn_addr)
        except zmq.ZMQError as e:
            return None, "Could not connect to {0}, err: {1}, {2}".format(
                                                            conn_addr, e, e.args)

        self.logger.info("************SENDING LAUNCH REQUEST  %s  %d  %s", 
                                machine_ip, _DEFAULT_TIMEOUT_MS, 'ms')

        send_msg(rq_sock, rq_message)
        result, details = self.poller.poll_recv(rq_sock, _DEFAULT_TIMEOUT_MS)

        rq_sock.close()

        if not result:

            details = details + "  [address was: {0}]".format(conn_addr)
            self.logger.error("@@@@@@@@@@@@   %s", details)
            return None, details
        else:
            result = self._mtool.unpack_msg(result)


        if result.type == 'rq_error':
            self.logger.error("REQUEST FAILED  %s", 
                                        result.err_code + ':' + result.details)
            return None, result.err_code + ':' + result.details
        elif result.type == 'launched_process_info':
            self.logger.info("REQUEST SUCCESS  %s", result.dict())
            process_desc = ProcessDescription(proc_type=result.proc_type,
                                            name=result.name,
                                            path=result.path,
                                            args=args,
                                            machine_ip=result.machine,
                                            pid=result.pid)


            new_proc = RemoteProcess(process_desc, conn_addr,
                                reg_timeout_desc=timeout_desc,
                                monitoring_optflags=monitoring_optflags,
                                logger=self.logger)

            if monitoring_optflags & PING:
                new_proc._ctx = self._ctx

            with self._proc_lock:
                self._processes[(result.machine, result.pid)] = new_proc

            new_proc.start_monitoring()

            return new_proc, None



UNKNOWN = 'unknown'
RUNNING = 'running'
FAILED = 'failed'
FINISHED = 'finished'
TERMINATED = 'terminated'
NON_RESPONSIVE = 'non_responsive'

PROCESS_STATUS = [UNKNOWN, RUNNING, FAILED, FINISHED, TERMINATED, NON_RESPONSIVE]

_REG_TIMER = 0

class Process(object):
    def __init__(self, proc_description,
                                reg_timeout_desc=None,
                                monitoring_optflags=PING,
                                logger=None):

        self.desc = proc_description

        self.must_register = reg_timeout_desc is not None
        self._status_lock = threading.RLock()
        self._status = UNKNOWN if self.must_register else RUNNING
        self._status_details = None

        self.ping_it = monitoring_optflags & PING
        self.check_returncode = monitoring_optflags & RETURNCODE if \
                                        self.desc.pid is not None else False

        self.logger = logger or get_logger(
                                'subprocess_monitor'+'-'+self.desc.name+'-'+str(self.desc.pid),
                                stream_level='info')
        self.set_registration_timeout_handler(reg_timeout_desc)
        self.registration_data = None

        self._stop_monitoring = False
        self._ping_thread = None
        self._ping_retries = 8
        self._returncode_thread = None
        self._mtool = OBCIMessageTool(message_templates)
        self._ctx = None
        self.rq_sock = None
        self._poller = PollingObject()

        self.delete = False


    @property
    def machine_ip(self):
        return self.desc.machine_ip

    @property
    def pid(self):
        return self.desc.pid

    @property
    def path(self):
        return self.desc.path

    @property
    def proc_type(self):
        return self.desc.proc_type

    @property
    def name(self):
        return self.desc.name

    def status(self):
        with self._status_lock:
            return self._status, self._status_details

    def set_registration_timeout_handler(self, reg_timeout_desc):
        with self._status_lock:
            self._status = UNKNOWN
            self._status_details = None
        self.must_register = reg_timeout_desc is not None
        self.reg_timeout_desc = reg_timeout_desc
        self.reg_timer = None if not self.must_register else \
                                        self.new_timer(self.reg_timeout_desc, _REG_TIMER)

        if self.must_register:
            self.reg_timer.start()

    def is_local(self):
        raise NotImplementedError()

    def timeout_handler(self, custom_method, args, type_):
        self._do_handle_timeout(type_)
        custom_method(*args)

    def _do_handle_timeout(self, type_):
        raise NotImplementedError()

    def new_timer(self, tim_desc, type_):
        return threading.Timer(tim_desc.timeout, self.timeout_handler,
                            [tim_desc.timeout_method, tim_desc.timeout_args, type_])

    def registered(self, reg_data):
        if self.reg_timer is not None:
            self.reg_timer.cancel()

        self.logger.info("{0} [{1}]  REGISTERED!!! {2}".format(
                                            self.name, self.proc_type, reg_data.machine_ip))
        #print "ping:", self.ping_it, "ret:", self.check_returncode
        with self._status_lock:
            self._status = RUNNING
        #TODO validate registration data
        self.registration_data = reg_data
        if self.ping_it:
            if not self._ctx:
                self._ctx = zmq.Context()
            self.rq_sock = self._ctx.socket(zmq.REQ)
            for addr in reg_data.rep_addrs:
                self.rq_sock.connect(addr)


    def stop_monitoring(self):
        if self.reg_timer:
            self.reg_timer.cancel()
            self.reg_timer = None
        self._stop_monitoring = True

        if self._ping_thread is not None:
            self.logger.info("%s, %s, %s",
                            self.proc_type, self.name ,"Joining ping thread")
            
            self._ping_thread.join()
        if self._returncode_thread is not None:
            self.logger.info("%s  %s  %s",
                            self.proc_type,self.name, "joining returncode thread")
            self._returncode_thread.join()
        self.logger.info("monitor for: %s, %s, %s", 
                    self.proc_type,self.name, "  ...monitoring threads stopped.")

    def finished(self):
        return self.popen_obj.returncode is not None and\
            (not self._ping_thread.is_alive()) and \
            (not self._returncode_thread.is_alive())

    def process_is_running(self):
        return self.popen_obj.returncode is None

    def start_monitoring(self):
        if self.ping_it:
            self._ping_thread = threading.Thread(target=self.ping_monitor, args=())
            self._ping_thread.daemon = True
            self._ping_thread.start()
        if self.check_returncode:
            self._returncode_thread = threading.Thread(target=self.returncode_monitor, args=())
            self._returncode_thread.daemon = True
            self._returncode_thread.start()

    def ping_monitor(self):
        is_alive = True
        while not self._stop_monitoring and is_alive:
            time.sleep(2)
            if self.rq_sock is not None:
                send_msg(self.rq_sock, self._mtool.fill_msg('ping'))
                result = None
                while self._ping_retries and not result and not self._stop_monitoring:
                    result, det = self._poller.poll_recv(socket=self.rq_sock, timeout=1500)
                if not result and not self._stop_monitoring:
                    self.logger.info("%s %s %s", 
                            self.proc_type, self.name, "NO RESPONSE TO PING!")
                    with self._status_lock:
                        if self._status not in [FAILED, FINISHED]:
                            self._status = NON_RESPONSIVE
                            self._status_details = 'ping response timeout'
                        print "status:", self._status
                        is_alive = False


    def returncode_monitor(self):
        raise NotImplementedError()

    def kill(self):
        raise NotImplementedError()

    def mark_delete(self):
        with self._status_lock:
            self.delete = True

    def marked_delete(self):
        with self._status_lock:
            return self.delete

class LocalProcess(Process):
    def __init__(self, proc_description, popen_obj, io_handler=None,
                                reg_timeout_desc=None,
                                monitoring_optflags=PING | RETURNCODE,
                                logger=None):
        self.popen_obj = popen_obj
        self.io_handler = io_handler

        super(LocalProcess, self).__init__(proc_description,
                                        reg_timeout_desc, monitoring_optflags,
                                        logger)

    def is_local(self):
        return True

    def _do_handle_timeout(self, type_):
        if type_ == _REG_TIMER:
            with self._status_lock:
                self._status = FAILED
                self._status_details = "Failed to register before timeout."

            self.kill()

    def tail_stdout(self, lines=DEFAULT_TAIL_RQ):
        if not self.io_handler:
            return None
        else:
            return self.io_handler.tail_stdout(int(lines))

    def kill(self):
        self.stop_monitoring()

        if self.io_handler is not None:
            if self.io_handler.is_running():
                self.io_handler.stop_output_handler()

        self.popen_obj.poll()
        with self._status_lock:
            if self.popen_obj.returncode is None:
                self.popen_obj.terminate()
            self.popen_obj.wait()

            if not self._status == NON_RESPONSIVE:
                self._status_details = -(self.popen_obj.returncode)
            self._status = TERMINATED

    def kill_with_force(self, timeout_s=0.1):
        self.stop_monitoring()

        if self.io_handler is not None:
            if self.io_handler.is_running():
                self.io_handler.stop_output_handler()

        self.popen_obj.poll()
        with self._status_lock:
            if self.popen_obj.returncode is None:
                self.popen_obj.terminate()
        time.sleep(timeout_s)
        self.popen_obj.poll()
        with self._status_lock:
            if self.popen_obj.returncode is None:
                self.logger.info("KILLING -9 PROCESS %s %s", self.pid, self.name)
                self.popen_obj.send_signal(signal.SIGKILL)
            self.popen_obj.wait()
            if not self._status == NON_RESPONSIVE:
                self._status_details = -(self.popen_obj.returncode)
            self._status = TERMINATED




    def returncode_monitor(self):
        # TODO just use wait() instead of poll()ing every 0.5s
        # self.popen_obj.wait()
        # code = self.popen_obj.returncode


        # print "[subprocess_monitor]",self.proc_type,"process", \
        #                 self.name, "pid", self.pid, "ended with", code
        # with self._status_lock:

        #     if code == 0:
        #         self._status = FINISHED
        #         self._status_details = ''
        #     elif code < 0:
        #         self._status = TERMINATED
        #         self._status_details = -code
        #     else:
        #         self._status = FAILED
        #         self._status_detals = self.tail_stdout(15)

        while not self._stop_monitoring:
            self.popen_obj.poll()
            code = self.popen_obj.returncode

            if code is not None:
                self.logger.info(self.proc_type + " process " + self.name +\
                                    " pid " + str(self.pid) + " ended with " + str(code))
                with self._status_lock:
                    self.popen_obj.wait()
                    if code == 0:
                        self._status = FINISHED
                        self._status_details = ''
                    elif code < 0:
                        self._status = TERMINATED
                        self._status_details = -code
                    else:
                        self._status = FAILED
                        self._status_detals = self.tail_stdout(15)
                break
            elif self.status()[0] == NON_RESPONSIVE:
                self.logger.warning(self.proc_type + "process" + self.name +\
                                         "pid" + self.pid + "is NON_RESPONSIVE")
                with self._status_lock:
                    self.popen_obj.poll()
                    if self.popen_obj.returncode is None:
                        self.popen_obj.terminate()
                        self._status = TERMINATED
                    self.popen_obj.wait()
            else:
                time.sleep(0.5)
        #print "[subprocess_monitor]",self.proc_type,self.name, self.pid,\
        #                             self.popen_obj.returncode, self._stop_monitoring
        if self.popen_obj.returncode is not None:
            self.popen_obj.wait()


class RemoteProcess(Process):
    def __init__(self, proc_description, rq_address,
                                reg_timeout_desc=None,
                                monitoring_optflags=PING,
                                logger=None):

        self.rq_address = rq_address
        self._ctx = None
        # returncode monitoring is not supported in remote processes..
        monitoring_optflags = monitoring_optflags & ~(1 << RETURNCODE)
        super(RemoteProcess, self).__init__(proc_description,
                                        reg_timeout_desc, monitoring_optflags,
                                        logger)


    def is_local(self):
        return False

    def _do_handle_timeout(self, type_):
        if type_ == _REG_TIMER:
            self._status = FAILED
            self._status_details = "Failed to register before timeout."

    def registered(self, reg_data):
        super(RemoteProcess, self).registered(reg_data)
        self.desc.pid = reg_data.pid

    def returncode_monitor(self):
        pass

    def kill(self):
        #send "kill" to the process or kill request to its supervisor?
        self.stop_monitoring()
        if not self._ctx:
            self._ctx = zmq.Context()
        rq_sock = self._ctx.socket(zmq.REQ)
        rq_sock.connect(self.rq_address)
        mtool = OBCIMessageTool(message_templates)
        poller = PollingObject()
        send_msg(rq_sock, self.mtool.fill_msg("kill_process", pid=self.pid, machine=self.machine_ip))
        res, det = poller.poll_recv(sock, timeout=5000)
        if res:
            res = mtool.unpack_msg(res)
            print "Response to kill request: ", res

            with self._status_lock:
                self._status = TERMINATED


class ProcessDescription(object):
    def __init__(self, proc_type, name, path, args, machine_ip, pid=None):
        self.proc_type = proc_type
        self.name = name
        self.uuid = None
        self.path = path
        self.args = args
        self.machine_ip = machine_ip
        self.pid = pid

    def dict(self):
        return dict(proc_type=self.proc_type,
                    name=self.name,
                    uuid=self.uuid,
                    path=self.path,
                    args=self.args,
                    machine_ip=self.machine_ip,
                    pid=self.pid)



class TimeoutDescription(object):
    def __init__(self, timeout=REGISTER_TIMEOUT, timeout_method=None,
                                                    timeout_args=[]):
        self.timeout = timeout
        self.timeout_method = timeout_method if timeout_method else \
                                    self.default_timeout_method
        self.timeout_args = timeout_args

    def default_timeout_method(self):
        return None

    def timer(self):
        return threading.Timer(self.timeout, self.timeout_method, self.timeout_args)

def default_timeout_handler():
    return TimeoutDescription()
