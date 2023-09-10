import os
import random
import string
import csv
import io

import sqlite3
from datetime import datetime

from flask import (
    Flask, send_from_directory, render_template, redirect, request, send_file,
    url_for
)


PROJECT_ROOT = os.path.dirname(os.path.realpath(__file__))
PLATFORMS = ['android', 'ios', 'iphone', 'windows', 'macintosh', 'macos']
DATABASE = os.path.join(PROJECT_ROOT, 'mappings.db')


class SQLiteContext:
    def __enter__(self):
        self.con = sqlite3.connect(DATABASE)
        self.cur = self.con.cursor()
        return self.con, self.cur

    def __exit__(self, *args):
        self.con.close()


app = Flask(__name__)
port = int(os.environ.get("PORT", 5000))
with SQLiteContext() as (con, cur):
    cur.execute('CREATE TABLE IF NOT EXISTS mappings(long, short)')
    cur.execute('CREATE TABLE IF NOT EXISTS logs(dttm, platform, short)')


def get_shorten_url(length=6):
    chars = string.ascii_uppercase + string.ascii_lowercase + string.digits
    short = "".join([random.choice(chars) for _ in range(length)])
    return short


# @app.route('/static/<path:path>')
# def serve_static(path):
#     return send_from_directory('static', path)


@app.route('/divos/export', methods=['GET'])
def export():
    with SQLiteContext() as (con, cur):
        maps = cur.execute(
            'SELECT * FROM mappings'
        )
        rows = maps.fetchall()
    with io.StringIO() as file:
        writer = csv.writer(file)
        writer.writerow(('long', 'short'))
        for row in rows:
            writer.writerow(row)
        mem = io.BytesIO()
        mem.write(file.getvalue().encode())
        mem.seek(0)
    return send_file(
        mem, as_attachment=True, download_name='mappings.csv',
        mimetype='text/csv'
    )


@app.route('/divos/shorten', methods=['GET', 'POST'])
def home():
    if request.method  == 'POST':
        long_url = request.form['url']
        short_url = get_shorten_url()
        with SQLiteContext() as (con, cur):
            res = cur.execute(
                'SELECT long FROM mappings WHERE short=?', [short_url]
            )
            while res.rowcount > 0:
                short_url = get_shorten_url()
                res = cur.execute(
                    'SELECT long FROM mappings WHERE short=?', [short_url]
                )
            cur.execute('INSERT INTO mappings VALUES (?, ?)', (long_url, short_url))
            con.commit()

        return render_template('success.html', short_url=request.url_root + short_url)
    return render_template('index.html')


@app.route('/<short_url>')
def url_redirect(short_url):
    now = datetime.now()
    with SQLiteContext() as (con, cur):
        res = cur.execute(
            "SELECT long FROM mappings WHERE short=?", [short_url]
        )
        res = res.fetchall()
        headers = "".join([a[1] for a in request.headers]).lower()
        platform = 'NA'
        for p in PLATFORMS:
            if p in headers:
                platform = p
                break
        cur.execute(
            "INSERT INTO logs VALUES (?, ?, ?)", [now, platform, short_url]
        )
        con.commit()

    if len(res) == 1:
        return redirect(res[0][0])
    return 'Not found', 404


@app.route('/<short_url>/edit', methods=['GET', 'POST'])
def edit(short_url):
    if request.method == 'POST':
        new_url = request.form['url']
        with SQLiteContext() as (con, cur):
            cur.execute(
                'UPDATE mappings SET long=? WHERE short=?',
                [new_url, short_url]
            )
            con.commit()
        return redirect(url_for('home'))

    with SQLiteContext() as (con, cur):
        res = cur.execute(
            "SELECT long FROM mappings WHERE short=?", [short_url]
        )
        res = res.fetchall()
    if len(res) != 1:
        return 'Not found', 404
    return render_template(
        'update.html', short_url=short_url, long_url=res[0][0]
    )


@app.route('/<short_url>/delete', methods=['GET', 'POST'])
def delete(short_url):
    if request.method == 'POST':
        with SQLiteContext() as (con, cur):
            cur.execute(
                "DELETE FROM mappings WHERE short=?", [short_url]
            )
            con.commit()
        return redirect(url_for('home'))

    with SQLiteContext() as (con, cur):
        res = cur.execute(
            "SELECT long FROM mappings WHERE short=?", [short_url]
        )
        res = res.fetchall()
    if len(res) != 1:
        return 'Not found', 404
    return render_template(
        'delete.html', short_url=short_url, long_url=res[0][0]
    )


@app.route('/<short_url>/stats')
def stats(short_url):
    context = dict()
    platforms = dict()
    total_count = 0
    with SQLiteContext() as (con, cur):
        res = cur.execute(
            'SELECT platform, count(*) AS count FROM logs WHERE short=? GROUP BY platform', [short_url]
        )
        for platform, count in res:
            platforms[platform] = count
            total_count += count
    context['short_url'] = short_url
    context['platforms'] = platforms
    context['total_count'] = total_count
    return render_template('stats.html', **context)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=port)