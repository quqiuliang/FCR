#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import signal
import logging
from concurrent.futures import ThreadPoolExecutor


from fbnet.command_runner_asyncio.CommandRunner.Command import Client as FcrClient
from .thrift_client import AsyncioThriftClient
from .command_session import CommandSession
from .base_service import ServiceObjMeta


class FcrServiceBase:
    '''
    Main Application object.

    This manages application resources and provides a common orchestraion point
    for the application modules.
    '''

    def __init__(self, app_name, config, loop=None):
        self._app_name = app_name
        self._config = config
        self._shutting_down = False
        self._stats_mgr = None

        self._loop = loop or asyncio.get_event_loop()

        executor = ThreadPoolExecutor(max_workers=config.max_default_executor_threads)
        self._loop.set_default_executor(executor)

        self._init_logging()

        self._loop.add_signal_handler(signal.SIGINT, self.shutdown)
        self._loop.add_signal_handler(signal.SIGTERM, self.shutdown)

        self.logger = logging.getLogger(self._app_name)

    def register_stats_mgr(self, stats_mgr):
        self.logger.info("Registering Counter manager")
        self._stats_mgr = stats_mgr
        ServiceObjMeta.register_all_counters(stats_mgr)

    @property
    def stats_mgr(self):
        return self._stats_mgr

    def incrementCounter(self, counter):
        self._stats_mgr.incrementCounter(counter)

    @property
    def config(self):
        return self._config

    @property
    def app_name(self):
        return self._app_name

    @property
    def loop(self):
        return self._loop

    def start(self):
        try:
            self._loop.run_forever()
        finally:
            pending_tasks = asyncio.Task.all_tasks(loop=self._loop)
            for task in pending_tasks:
                task.cancel()
            self._loop.run_until_complete(
                asyncio.gather(*pending_tasks, return_exceptions=True))
            self._loop.close()

    async def _clean_shutdown(self):
        try:
            coro = CommandSession.wait_sessions('Shutdown', loop=self.loop)
            await asyncio.wait_for(coro,
                                   timeout=self.config.exit_max_wait,
                                   loop=self.loop)

        except asyncio.TimeoutError:
            self.logger.error("Timeout waiting for sessions, shutting down anyway")

        finally:
            self.terminate()

    def terminate(self):
        '''
        Terminate the application. We cancel all the tasks that are currently active
        '''
        self.logger.info("Terminating")

        pending_tasks = asyncio.Task.all_tasks(loop=self.loop)
        for t in pending_tasks:
            t.cancel()

        self.loop.stop()

    def shutdown(self):
        '''initiate a clean shutdown'''
        if not self._shutting_down:
            self._shutting_down = True
            asyncio.ensure_future(self._clean_shutdown(), loop=self.loop)
        else:
            # Forcibly shutdown.
            self.terminate()

    def _init_logging(self):

        level = getattr(logging, self.config.log_level.upper(), None)

        if not isinstance(level, int):
            raise ValueError('Invalid log level: %s' % self.config.log_level)

        logging.basicConfig(level=level)

    def decrypt(self, data):
        '''helper method to decrypt data.

        The default implementation doesn't do anything. Override this method to
        implement security according to your needs
        '''
        return data

    def get_fcr_client(self, timeout=None):
        '''
        Get a FCR client for your service.

        This client is used to distribute requests for bulk calls
        '''
        return AsyncioThriftClient(
            FcrClient, 'localhost', self.args.port,
            counter_mgr=self, timeout=timeout, loop=self.loop)

    def check_ip(self, ipaddr):
        '''
        Check if ip address is usable.

        You will likely need to override this function to implement the ip
        validation logic. For eg. a service could periodically check what ip
        addresses are reachable. The application can then use this data to
        filter out non-reachable addresses.

        The default implementation assumes that everything is reachable
        '''
        return True

    def add_stats_counter(self, counter, stats_types):
        # Currently this only support simple counter, stats parameter are
        # ignored
        self.logger.info(
            "stats counter not supported: %s %r", counter, stats_types)
        self.counters.resetCounter(counter)

    def get_http_proxy_url(self, host):
        '''build a url for http proxy'''
        raise NotImplemented("Proxy support not implemented")