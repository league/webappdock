#!/usr/bin/env python
# -*- coding: utf-8 -*-
# server.py • an example server

import BaseHTTPServer
import os
import psycopg2
import sys
import time

HOST_NAME = ''
PORT_NUMBER = 8000
VARS = ('FLOOP', 'BRUP', 'GORP')

def log(format, *args):
    sys.stderr.write('%s: %s\n' % (time.asctime(), format % args))
    sys.stderr.flush()

class MyHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        log(format, *args)

    def do_GET(s):
        """Respond to a GET request."""
        s.send_response(200)
        s.send_header("Content-type", "text/plain")
        s.end_headers()
        s.wfile.write("The server is now up!\n")
        for k in VARS:
            s.wfile.write("%s is %s\n" % (k, os.environ.get(k)))
        s.wfile.write("You accessed path: %s\n" % s.path)
        cursor = conn.cursor()
        cursor.execute('update visits set counter = counter+1 where path = %s',
                       (s.path,))
        if cursor.rowcount == 0:
            cursor.execute('insert into visits (path) values (%s)', (s.path,))
        conn.commit()
        cursor.execute('select path, counter from visits order by path')
        for row in cursor.fetchall():
            s.wfile.write("%s -> %s time%s\n" %
                          (row[0], row[1], '' if int(row[1])==1 else 's'))
        cursor.close()


if __name__ == '__main__':
    try:
        sys.stderr = open(sys.argv[1], 'a')
    except IndexError:
        pass

    conn_string = "host='%s' dbname='my_database' user='%s' password='%s'" %\
                  (os.environ['DB_PORT_5432_TCP_ADDR'],
                   os.environ['DB_ENV_USER'],
                   os.environ['DB_ENV_PASS'])
    print "Connecting to database..."
    conn = psycopg2.connect(conn_string)
    cursor = conn.cursor()
    print "Connected!\n"
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS visits
        (path VARCHAR(255) PRIMARY KEY,
         counter INT NOT NULL DEFAULT 1)''')
    conn.commit()
    cursor.close()
    server_class = BaseHTTPServer.HTTPServer
    httpd = server_class((HOST_NAME, PORT_NUMBER), MyHandler)
    log('Server starts - %s:%s', HOST_NAME, PORT_NUMBER)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    log('Server stops - %s:%s', HOST_NAME, PORT_NUMBER)
    sys.stderr.close()
