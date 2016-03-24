#!/usr/bin/env python
#
# Cachelot server memory consumption measurement
#

import sys
import string
import random
import os
import subprocess
import shlex
import time
import logging
import atexit
import memcached


log = logging.getLogger()

SELF, _ = os.path.splitext(os.path.basename(sys.argv[0]))
BASEDIR = os.path.normpath(os.path.dirname(os.path.abspath(sys.argv[0])) + '/..')
CACHELOTD = os.path.join(BASEDIR, 'bin/RelWithDebugInfo/cachelotd')
MEMCACHED = '/usr/bin/memcached'
NUM_RUNS = 10

KEY_ALPHABET = string.ascii_letters + string.digits

VALUE_RANGES = { 'small': (10, 1024),
                 'medium': (1024, 4096),
                 'large' :(4096, 1000000),
                 'all': (10, 100000)}

MAX_DICT_MEM = 1024*1024 * 100  # Mb


FILTER_STATS = frozenset([
    'cmd_get', 'get_hits', 'get_misses',
    'used_memory',
    'total_requested', 'total_served',
    'evictions',
    'curr_items', 'total_items',
    'evicted_unfetched',
])


def setup_logging():
    """
    Setup python logging module (destinations like terminal output and file, formatting, etc.)
    """
    # logging setup
    logging_default_level = logging.DEBUG
    logging_console_enable = True
    logging_format = '%(levelname)s: %(message)s'
    logging_file_enable = True
    logging_file_dir = './'
    logging_file_name = SELF + time.strftime('_%Y%b%d-%H%M%S') + '.log'


    logging.STAT = logging.DEBUG + 1
    logging.addLevelName(logging.FATAL, 'F')
    logging.addLevelName(logging.ERROR, 'E')
    logging.addLevelName(logging.WARN,  'W')
    logging.addLevelName(logging.INFO,  'I')
    logging.addLevelName(logging.DEBUG, 'D')
    logging.addLevelName(logging.STAT,  'S')

    root_logger = logging.getLogger()
    formatter = logging.Formatter(logging_format)
    # Console output
    if logging_console_enable:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root_logger.addHandler(console)
    # Log file
    if logging_file_enable:
        filename = os.path.join(logging_file_dir, logging_file_name)
        logfile = logging.FileHandler(filename)
        logfile.setFormatter(formatter)
        root_logger.addHandler(logfile)
    atexit.register(logging.shutdown)
    root_logger.setLevel(logging_default_level)


def random_key():
    length = random.randint(10, 60)
    return ''.join(random.choice(KEY_ALPHABET) for _ in range(length))


def random_value(minlen, maxlen):
    length = random.randint(minlen, maxlen)
    return ''.join(map(chr, (random.randint(0,255) for _ in xrange(length))))


def log_stats(mc):
    for stat, value in mc.stats():
        if stat in FILTER_STATS:
            log.log(logging.STAT, '%30s:  %s' % (stat, value))


def shell_exec(command):
    devnull = open(os.devnull, 'w')
    return subprocess.Popen(args=shlex.split(command), stdout=devnull, stderr=devnull)


def create_kv_data(range_name):
    minval, maxval = VALUE_RANGES[range_name]
    current_dict_mem = 0
    in_memory_kv = []
    log.info('Creating KV data for the range "%s" [%d:%d]' %(range_name, minval, maxval))
    start_time = time.time()
    while current_dict_mem < MAX_DICT_MEM:
        k = random_key()
        current_dict_mem += len(k)
        v = random_value(minval, maxval)
        current_dict_mem += len(v)
        in_memory_kv.append( (k, v) )
    took_time = time.time() - start_time
    log.debug('  Took: %.2f sec', took_time)
    log.info('Local effective memory: %d (%d items).', current_dict_mem, len(in_memory_kv))

    return in_memory_kv


def execute_test(mc, kv_data):
    for run_no in range(NUM_RUNS):
        start_time = time.time()
        log.debug('Fill-in caching server ...')
        for k, v in kv_data:
            mc.set(k, v)
        log.debug('  Took: %.2f sec', time.time() - start_time)
        log.debug('Checking caching server ...')
        effective_memory = 0
        start_time = time.time()
        for k, local_val in kv_data:
            external_val = mc.get(k)
            if not external_val:
                # item was evicted, move along
                continue
            effective_memory += len(k) + len(local_val)

        log.info('External effective memory: %d.', effective_memory)
        log.debug('  Took: %.2f sec', time.time() - start_time)

        # print statistics
        log_stats(mc)
        random.shuffle(kv_data)


def execute_test_for_values_range(range_name):
    log.info('*' * 60)
    # Create test data
    in_memory_kv = create_kv_data(range_name)

    # Run dataset on cachelot
    log.info("*** CACHELOT")
    cache_process = shell_exec(CACHELOTD)
    time.sleep(3)
    mc = memcached.connect_tcp('localhost', 11211)
    execute_test(mc, in_memory_kv)
    cache_process.terminate()
    time.sleep(2)
    log.info('*' * 60)

    # Run dataset on memcached
    log.info("*** MEMCACHED")
    cache_process = shell_exec(MEMCACHED + ' -p 11212 -n 32 -f 1.05')
    time.sleep(3)
    mc = memcached.connect_tcp('localhost', 11212)
    execute_test(mc, in_memory_kv)
    cache_process.terminate()
    time.sleep(2)
    log.info('*' * 60)
    log.info('\n\n')


def main():
    for range in ['small', 'medium', 'large', 'all']:
        execute_test_for_values_range(range)


if __name__ == '__main__':
    setup_logging()
    main()
