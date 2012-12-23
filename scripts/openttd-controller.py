#!/usr/bin/env python2.6


from datetime import datetime
from optparse import OptionParser
from threading import Thread
import logging
import os
import signal
import subprocess
import sys
import time


# we need a quite new python version
try:
    subprocess.Popen.terminate
except AttributeError:
    print 'Your python version is too old. Use at least python2.6'
    sys.exit(0)


SCRIPTDIR = os.path.dirname(os.path.abspath(__file__))


def threaded(name):
    def _wrap(func):
        def _threader(*args, **kwargs):
            t = Thread(name=name,
                       target=func,
                       args=args,
                       kwargs=kwargs)
            t.start()
            return t
        return _threader
    return _wrap


class DedicatedServerController(object):
    """Controls the dedicated server.
    """

    def __init__(self):
        # setup logging
        self.logger = logging.getLogger('openttd-dedicated')
        self.logger.setLevel(logging.WARNING)
        self.log_handler = logging.StreamHandler()
        self.log_handler.setLevel(logging.WARNING)
        self.log_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        self.log_handler.setFormatter(self.log_formatter)
        self.logger.addHandler(self.log_handler)

        # setup optparse
        usage = 'usage: %prog {create|load} DIR'
        self.optparse = OptionParser(usage=usage)

        self.optparse.add_option('-t', '--starting-year',
                                 dest='startingyear',
                                 type='int',
                                 default=None,
                                 help='Set starting year')

        self.optparse.add_option('-p', '--password',
                                 dest='password',
                                 default=None,
                                 help='Password to join server')

        self.optparse.add_option('-c', '--use-config',
                                 dest='config', metavar='FILE',
                                 help='Use openttd.cfg FILE',
                                 default='')

        self.optparse.add_option('-a', '--autosave',
                                 dest='autosave', type='int',
                                 help='Autosave timeout in minutes'
                                 ' (Default: 30 minutes)',
                                 default=30)

        self.optparse.add_option('-f', '--force',
                                 dest='force', action='store_true',
                                 help='Do not quit when creating a game and '
                                 'there are already savegames.')

        self.optparse.add_option('-d', '--debug',
                                 dest='debug', action='store_true',
                                 help='Debug log level.')

        self.optparse.add_option('-s', '--server',
                                 dest='server', metavar='FILE',
                                 help='Path to openttd server executable.',
                                 default='openttd')

        self.optparse.add_option('-u', '--personal-dir',
                                 dest='personal_dir',
                                 help='Persnal directory, where the openttd.cfg '
                                 'is managed by this script.',
                                 default=SCRIPTDIR)

    def __call__(self):
        self.options, self.args = self.optparse.parse_args()

        if self.options.debug:
            self.logger.setLevel(logging.DEBUG)
            self.log_handler.setLevel(logging.DEBUG)

        if len(self.args) == 2:
            self.action = self.args[0]
            self.directory = self.args[1]

        elif len(self.args) == 1 and self.args[0] == 'load':
            self.action = self.args[0]
            self.directory = 'game.last'

        elif len(self.args) == 1:
            self.optparse.print_help()
            self.quit('Unkown or missing command or directory. '
                      'See usage.')

        elif len(self.args) == 0:
            if os.path.exists('game.last'):
                self.action = 'load'
                self.directory = 'game.last'
            else:
                self.action = 'create'
                self.directory = 'game.001'

        else:
            self.optparse.print_help()
            self.quit('Unkown or missing command or directory. '
                      'See usage.')

        if self.action == 'create':
            self.action_create()

        elif self.action == 'load':
            self.action_load()

    def action_create(self):
        """Action for creating a new game.
        """
        self.logger.debug('Create a new game in directory %s' %
                          self.directory)

        if not os.path.exists(self.directory):
            # directory missing - create it
            self.logger.debug('Creating directory %s' % self.directory)
            os.mkdir(self.directory)

        elif not os.path.isdir(self.directory):
            # its not a directory - quit
            self.quit('%s is not a directory!' % self.directory)

        # if there are already savegames in the directory we quit
        if len([name for name in os.listdir(self.directory)
                if name.endswith('.sav')]) > 0:
            if not self.options.force:
                self.quit('Dont be chaotic: %s contains already savegames.'
                          'Use "load" action or another directory.')

        self.load_config()

        try:
            self.proc = ProcessController(
                controller=self,
                directory=self.directory,
                autosave=self.options.autosave,
                startingyear=self.options.startingyear,
                password=self.options.password)
            self.proc.runserver()

        except:
            self.update_config()
            raise

        else:
            self.update_config()
            self.logger.debug('Shutting down.')

    def action_load(self):
        """The load action loads a saved game.
        """
        self.logger.debug('Load game from directory %s' % self.directory)

        if not os.path.isdir(self.directory):
            self.quit('Could not find directory %s' % self.directory)

        # get the savegames
        savegames = [os.path.abspath(os.path.join(self.directory, name))
                     for name in os.listdir(self.directory)
                     if name.endswith('.sav')]

        if not len(savegames):
            self.quit('No savegames found in %s' % self.directory)

        # sort the savegames by date, oldest first
        savegames.sort(lambda a,b: cmp(os.stat(a)[8], os.stat(b)[8]))

        self.load_config()

        try:
            self.proc = ProcessController(
                controller=self,
                directory=self.directory,
                autosave=self.options.autosave,
                savegame=savegames[-1],
                startingyear=self.options.startingyear,
                password=self.options.password)
            self.proc.runserver()

        except:
            self.update_config()
            raise

        else:
            self.update_config()
            self.logger.debug('Shutting down.')

    def load_config(self):
        """Loads the config.
        """
        runtimeconfig = os.path.join(self.options.personal_dir, 'openttd.cfg')
        defaultconfig = os.path.join(SCRIPTDIR, 'default.cfg')
        gameconfig = os.path.join(self.directory, 'openttd.cfg')

        sourceconfig = None

        if self.options.config:
            # if a config is defined by command options, use this
            # config file as source file.
            path = os.path.abspath(self.options.config)
            if not os.path.exists(path) or \
                    not os.path.isfile(path):
                self.quit('Not a configuration file: %s' % path)
            else:
                sourceconfig = path

        elif os.path.isfile(gameconfig):
            # use the already existing game config
            sourceconfig = gameconfig

        elif os.path.isfile(defaultconfig):
            # use the default config
            sourceconfig = defaultconfig

        else:
            # use the runtimeconfig
            sourceconfig = runtimeconfig

        # check the source config
        if not os.path.exists(sourceconfig):
            self.quit('Could not find suitable configuration.'
                      'Expected at least one at %s' % sourceconfig)

        # copy the sourceconfig into runtimeconfig - this is which
        # the server will use
        if sourceconfig != runtimeconfig:
            self.logger.debug('Using %s as runtime config.' %
                              sourceconfig)
            file_ = open(runtimeconfig, 'w')
            file_.write(open(sourceconfig).read())
            file_.close()

        # also copy the sourceconfig into gameconfig as backup
        if sourceconfig != gameconfig:
            sourcedata = open(sourceconfig).read()
            if os.path.isfile(gameconfig):
                gamedata = open(gameconfig).read()
            else:
                gamedata = ''

            if os.path.isfile(gameconfig) and gamedata != sourcedata:
                # need a backup
                bakpath = os.path.join(self.directory,
                                       'openttd.cfg-%s' %
                                       datetime.now().strftime('%Y%m%d-%H%m%S'))
                self.logger.debug('Backing up game config into %s' % bakpath)
                file_ = open(bakpath, 'w')
                file_.write(gamedata)
                file_.close()

            self.logger.debug('Copying config into game directory: %s -> %s' %
                              (sourceconfig, gameconfig))
            file_ = open(gameconfig, 'w')
            file_.write(sourcedata)
            file_.close()

    def update_config(self):
        """Update config into game directory on exit.
        """
        runtimeconfig = os.path.join(self.options.personal_dir, 'openttd.cfg')
        gameconfig = os.path.join(self.directory, 'openttd.cfg')
        self.logger.debug('Saving current game config in game directory: '
                          '%s -> %s' % (runtimeconfig, gameconfig))
        file_ = open(gameconfig, 'w')
        file_.write(open(runtimeconfig).read())
        file_.close()

    def quit(self, message):
        self.logger.error(message)


class ProcessController(object):
    """Starts and controlls the openttd process. It is able to run
    periodic commands and passes user interaction to the process.
    """

    _command_registry = []

    @classmethod
    def registerCommand(cls, command):
        cls._command_registry.append(command)

    def __init__(self, controller, directory, autosave, savegame=None,
                 startingyear=None, password=None):

        if not os.path.isdir(directory):
            raise ValueError('Directory does not exist: %s' %
                             self.directory)

        self.directory = directory
        self.autosave = int(autosave)
        self.startingyear = startingyear and int(startingyear) or None
        self.password = password or None
        self.controller = controller
        self.logger = controller.logger
        self.savegame = savegame

    def runserver(self):
        """Starts the dedicated server according to the configuration.
        """
        args = [self.controller.options.server, '-D']
        if self.startingyear:
            args += ['-t', str(self.startingyear)]
        if self.password:
            args += ['-p', self.password]
        if self.savegame:
            args += ['-g', self.savegame]

        if self.directory != 'game.last':
            if os.path.exists('game.last'):
                os.system('rm game.last')
            os.system('ln -s %s game.last' % self.directory)

        cmd = ' '.join(args)
        self.logger.debug('Open process with args: %s' % cmd)
        self.proc = subprocess.Popen(args,
                                     stdin=subprocess.PIPE)

        self.shell()
        self.autosave_cronjob(self.autosave)

        def terminate(signum, frame):
            quit_command(self, self.logger, '')

        signal.signal(signal.SIGTERM, terminate)
        signal.signal(signal.SIGINT, terminate)

        # wait for termination
        while True:
            try:
                if not self.proc.poll() == None or not self.running:
                    break
            except KeyboardInterrupt:
                break

    @threaded('openttd dedicated shell')
    def shell(self):
        """Provide a shell
        """
        self.running = True

        try:
            while self.proc.poll() == None and self.running:
                input = raw_input('').strip()
                if not input:
                    continue

                if ' ' in input:
                    cmd, args = input.split(' ', 1)
                else:
                    cmd, args = input, ''

                func = None
                for command in self._command_registry:
                    if cmd in command['names']:
                        func = command['func']

                if func:
                    func(self, self.logger, args)
                else:
                    print 'Unknown command, use "help"'

        except KeyboardInterrupt:
            quit_command(self, self.logger, '')

        except:
            if self.proc.poll() == None:
                self.proc.terminate()
            raise

        else:
            if self.proc.poll() == None:
                self.proc.terminate()

    @threaded('openttd dedicated autosave job')
    def autosave_cronjob(self, timeout=30):
        """Creates a autosave every `timeout` minutes.
        """
        timeout_sec = timeout * 60

        self.logger.info('Setting up autosave cronjob with an '
                         'interval of %i minutes' % timeout)

        try:
            while True:
                for sec in range(timeout_sec):
                    if self.proc.poll() != None or not self.running:
                        return

                    time.sleep(1)

                self.logger.debug('Executing autosave.')
                save_command(self, self.logger, '')

        except KeyboardInterrupt:
            return

    def send_command(self, cmd):
        """Sends a command to the openttd process.
        """
        self.proc.stdin.write(cmd.strip() + '\n')
        self.proc.stdin.write('\n')


def command(names, help):
    def _wrap(func):
        ProcessController.registerCommand({
                'func': func,
                'names': names,
                'help': help
                })
        return func
    return _wrap


@command(['help','h'], 'Print help text.')
def help_command(controller, logger, args):
    for cmd in controller._command_registry:
        print ', '.join(cmd['names']).ljust(10), cmd['help']


@command(['quit', 'q'], 'Terminate server.')
def quit_command(controller, logger, args):
    save_command(controller, logger, args)
    controller.send_command('quit')
    controller.running = False
    time.sleep(5)
    sys.exit(0)


@command(['save', 's'], 'Save current game state.')
def save_command(controller, logger, args):
    # filename pattern: savegame-[AI]-[Date]-[Time].sav
    # AI: auto incremented number
    directory = os.path.abspath(controller.directory)

    # the old style pattern misses the auto increment number - we
    # may need to fix the filenames
    filenames = filter(lambda name: name.startswith('savegame-') \
                           and name.endswith('.sav'),
                       os.listdir(directory))

    # create a number/filename mapping
    savegame_map = {}
    for name in filenames:
        savegame_map[int(name.split('-')[1])] = name

    # number for next savegame
    next = savegame_map and max(savegame_map.keys()) + 1 or 1

    # invoke a savegame
    stamp = datetime.now().strftime('%Y%m%d-%H%m%S')
    name = 'savegame-%i-%s' % (next, stamp)
    path = os.path.join(directory, name)
    logger.debug('Savegame to %s.sav' % path)
    controller.send_command('save %s' % path)

    # cleanup old savegames with strategy:
    # - keep the last 10 saves
    # - keep every 10th save of the last 100
    # - keep every 100th of the ones older than the last 100
    # Example with 1243 savegames, keeping following:
    # - 1243, 1242, 1241, 1240, 1239, 1238, 1237, 1236, 1235, 1234
    # - 1230, 1220, 1210, 1200, 1190, 1180, 1170, 1160, 1150, 1140
    # - 1100, 1000, 900,  800,  700,  600,  500,  400,  300,  200

    logger.debug('invoking cleanup')

    current = next - 1
    mod = 1
    keep = 10
    while current > 0:
        if current % mod == 0:
            # keeping this one
            keep -= 1
        elif current not in savegame_map:
            # file is missing - skip
            pass
        else:
            # remove it
            filename = savegame_map[current]
            logger.debug('Removing savegame %s' % filename)
            os.remove(os.path.join(directory, filename))

        if keep == 0:
            mod *= 10
            if mod < 100:
                keep = 10
            else:
                keep = 100

        current -= 1

    # wait untill the file is there.
    timeout = 100
    for i in range(timeout):
        if os.path.isfile(path + '.sav'):
            break
        if i == timeout - 1:
            logger.error('Waited %i seconds for game to save '
                         'but file still missing: %s.sav' % path)
            break
        time.sleep(1)


@command(['exec', 'x'], 'Send rcon command to openttd server.')
def exec_command(controller, logger, args):
    controller.send_command(args)

@command(['pdb'], 'Start python debugger.')
def pdb_command(controller, logger, args):
    import pdb
    pdb.set_trace()


if __name__ == '__main__':
    DedicatedServerController()()
