#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# CTForge: Forge your own CTF.

# Copyright (C) 2016-2019  Marco Squarcina
# Copyright (C) 2016-2019  Mauro Tempesta
# Copyright (C) 2016-2019  Lorenzo Veronese

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.


import os
import re
import sys
import csv
import pkgutil
import argparse
import bcrypt
import json
from shutil import copy2
from getpass import getpass
from ctforge.database import db_connect

from ctforge import app, utils, database

def db_create_schema():
    db_conn = database.db_connect('postgres')
    db_conn.autocommit = True
    with db_conn.cursor() as cur:
        cur.execute('DROP DATABASE IF EXISTS {}'.format(app.config['DB_NAME']))
        cur.execute("CREATE DATABASE {} WITH ENCODING 'UTF8'".format(app.config['DB_NAME']))
    db_conn.close()

    db_conn = database.db_connect()
    with db_conn.cursor() as cur:
        cur.execute(pkgutil.get_data('ctforge', 'db/schema.sql'))
    db_conn.commit()
    db_conn.close()

def db_create_procedures():
    db_conn = database.db_connect()
    with db_conn.cursor() as cur:
        cur.execute(pkgutil.get_data('ctforge', 'db/procedures.sql'))
    db_conn.commit()
    db_conn.close()

def db_add_admin(name, surname, nickname, mail, affiliation, password):
    db_add_user(name, surname, nickname, mail, affiliation, password, admin=True, hidden=True)

def db_add_user(name, surname, nickname, mail, affiliation, password, admin=False, hidden=False, team_id=None):
    db_conn = database.db_connect()
    with db_conn.cursor() as cur:
        cur.execute((
            'INSERT INTO users (team_id, name, surname, nickname, mail, affiliation, password, admin, hidden) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)'),
            [team_id, name, surname, nickname, mail, affiliation, bcrypt.hashpw(password, bcrypt.gensalt()),
             admin, hidden])
    db_conn.commit()
    db_conn.close()

def exit_on_resp(resp):
    if resp not in ['y' , 'Y']:
        print('Goodbye...')
        sys.exit(1)

def ask(question, answer=None):
    print(question, end=' ')
    if answer is not None:
        print()
        return answer
    else:
        return input()

def init(args):
    confile = os.path.expanduser('~/.ctforge/ctforge.conf')
    print(('\nWelcome to the installation script of CTForge\n'
           'Please backup your {} file before continuing.\n'.format(confile)))
    
    resp = ask('Do you want to proceed? (y/n)', 'y' if args.yes else None)
    exit_on_resp(resp)
    
    print('[*] Creating database schema')
    db_create_schema()

    print('[*] Installing SQL procedures')
    db_create_procedures()

    print('[*] Adding an administrative user')

    admin_name = ask('    name:', args.name)
    admin_surname = ask('    surname:', args.surname)
    admin_nickname = ask('    nickname:', args.nickname)
    admin_mail = ask('    mail:', args.mail)
    if args.password is None:
        admin_password = getpass('    password: ')
        admin_password_rep = getpass('    re-enter the password: ')
        if admin_password != admin_password_rep:
            sys.stderr.write("Passwords don't match, aborting!")
            sys.exit(1)
    else:
        admin_password = args.password
    admin_affiliation = None

    db_add_admin(admin_name, admin_surname, admin_nickname,
                 admin_mail, admin_affiliation, admin_password)

    resp = ask('Save configuration to {} ? (y/n)'.format(confile), 'y' if args.yes else None)
    exit_on_resp(resp)
    os.makedirs(os.path.dirname(confile), mode=0o700, exist_ok=True)
    try:
        copy2(args.conf, confile)
    except Exception as e:
        sys.stderr.write('Error: "{}" "{}" "{}"\n'.format(args.conf, confile, e))

    if app.config['LOG_FILE'] is not None:
        logfile = app.config['LOG_FILE']
        if not os.path.exists(logfile):
            logdir = os.path.dirname(logfile)
            resp = ask('Create log dir {} ? (y/n)'.format(logdir), 'y' if args.yes else None)
            exit_on_resp(resp)
            os.makedirs(logdir, mode=0o700, exist_ok=True)
            resp = ask('Create log file {} ? (y/n)'.format(logfile), 'y' if args.yes else None)
            exit_on_resp(resp)
            os.mknod(logfile, mode=0o600)

def run(args):
    debug = args.debug or app.config['DEBUG']
    app.run(host=args.host, port=args.port, debug=debug, threaded=True)

def imp(args):
    if args.users:
        print('Importing users...')
        users = csv.reader(args.users, delimiter=',', quotechar='"')
        for i,user in enumerate(users):
            print("{}".format(i))
            sys.stdout.flush()
            db_add_user(name=user[0], surname=user[1], nickname=None, mail=user[3], affiliation=user[4], password=user[5])
        args.users.close()
        print('Done!')

def imp_chal(chal_info_file, public_folder):
    chal_info = json.loads(chal_info_file.read())
    print('Importing challenge `{}`...'.format(chal_info['title']))
    db_conn = db_connect()
    db_conn.autocommit = True
    with db_conn.cursor() as cur:
        # NOTE: need to manually copy public files to the webserver public folder
        description = chal_info['description']
        if chal_info['public_files']:
            description += '<br><br><p><b>Public Files:</b></p><ul>'
            for f in chal_info['public_files']:
                description += '<li><a href="{}">{}</a></li>'.format(
                    os.path.join(public_folder,f), f)
            description += '</ul>'
        cur.execute('INSERT INTO challenges (name, description, flag, points, '
                    'tags, active, hidden,writeup) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                    [chal_info['title'], description, chal_info['flag'],
                     chal_info['points'], '/'.join(chal_info['tags']),
                     False, True, False])
    db_conn.close()
    print('Done.')

def parse_args():
    parser = argparse.ArgumentParser(description='Initialize or run CTForge')
    parser.add_argument('-c', '--conf', dest='conf', type=str,
        default='ctforge.conf', help='Configuration file')
    subparsers = parser.add_subparsers(dest='command')

    parser_init = subparsers.add_parser('init', help='Install and initialize the framework')
    parser_init.add_argument('-n', '--name', type=str, help='Administrator name')
    parser_init.add_argument('-s', '--surname', type=str, help='Administrator surname')
    parser_init.add_argument('-k', '--nickname', type=str, help='Administrator nickname')
    parser_init.add_argument('-m', '--mail', type=str, help='Administrator mail')
    parser_init.add_argument('-p', '--password', type=str, help='Administrator password (unsafe)')
    parser_init.add_argument('-y', '--yes', action='store_true', help='Say Yes to all questions')

    parser_run = subparsers.add_parser('run', help='Run an instance of the framework for development purposes')
    parser_run.add_argument('-H', '--host', type=str, help='Hostname to listen on', default='127.0.0.1')
    parser_run.add_argument('-P', '--port', type=int, help='Port to listen on', default=5000)
    parser_run.add_argument('-D', '--disable-debug', dest='debug', action='store_false', help='Disable debug mode')

    parser_import = subparsers.add_parser('import_users', help='Import users')
    parser_import.add_argument('-u', '--users', type=argparse.FileType('r', encoding='UTF-8'),
                               help='A csv file of users to import. The supported format is: name, surname, nickname, mail, affiliation, password. No header and comma as separator')


    parser_challenge = subparsers.add_parser('import_challenge', help='Import Challenge')
    parser_challenge.add_argument('challenge', type=argparse.FileType('r'), help='Challenges folder in which each subdirectory contains an `info.json` file')
    parser_challenge.add_argument('--public-files-uri', default='/data/public_files/', help='Webserver public folder')

    return parser.parse_args()

def main():
    global config

    args = parse_args()
    if args.conf is not None:
        print('[*] Reading configuration from {}'.format(args.conf))
        sys.stdout.flush()

        try:
            config = utils.parse_conf(args.conf)
        except Exception:
            sys.stderr.write('Invalid configuration file, aborting!')
            sys.exit(1)

        # update the global app configuration
        app.config.update(config)

    if args.command == 'run':
        run(args)
    elif args.command == 'init':
        init(args)
    elif args.command == 'import_users':
        imp(args)
    elif args.command == 'import_challenge':
        imp_chal(args.challenge, args.public_files_uri)
    else:
        sys.stderr.write("... Doing nothing, bye\n")
        sys.exit(1)

    sys.exit(0)

if __name__ == '__main__':
    main()
