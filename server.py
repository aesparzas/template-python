import os
import random
import string
import csv
import io
import sqlite3
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

from flask import (
    Flask, send_from_directory, render_template, redirect, request, send_file,
    url_for
)
from flask_cors import CORS
import psycopg

PROJECT_ROOT = os.path.dirname(os.path.realpath(__file__))
PLATFORMS = ['android', 'ios', 'iphone', 'windows', 'macintosh', 'macos']
DATABASE_CONFIGS = {
    'name': os.environ.get('DB_NAME'),
    'host': os.environ.get('DB_HOST'),
    'user': os.environ.get('DB_USER'),
    'password': os.environ.get('DB_PASS'),
    'port': os.environ.get('DB_PORT')
}
DATABASE_DEFAULT = os.path.join(PROJECT_ROOT, 'mappings.db')


class DBContext:
    def __enter__(self):
        if all([bool(v) for v in DATABASE_CONFIGS.values()]):
            self.con = psycopg.connect(
                database=DATABASE_CONFIGS['name'],
                host=DATABASE_CONFIGS['host'],
                user=DATABASE_CONFIGS['user'],
                password=DATABASE_CONFIGS['password'],
                port=DATABASE_CONFIGS['port'],
                sslmode='require',
            )
        else:
            self.con = sqlite3.connect(DATABASE_DEFAULT)
        self.cur = self.con.cursor()
        if isinstance(self.con, psycopg.extensions.connection):
            self.param_char = "%s"
        else:
            self.param_char = "?"
        return self.con, self.cur, self.param_char

    def __exit__(self, *args):
        self.con.commit()
        self.con.close()


port = int(os.environ.get("PORT", 5000))
root_url = os.environ.get("ROOT_URL")
admin_site = os.environ.get('ADMIN_SITE', 'admin')
max_length = 16  # should not be changed
app = Flask(__name__)
CORS(app)


with DBContext() as (con, cur, param_char):
    cur.execute('CREATE TABLE IF NOT EXISTS mappings('
                'long VARCHAR(1000) NOT NULL, '
                'short VARCHAR(16) UNIQUE, '
                'nmbr VARCHAR(16), '
                'descr VARCHAR(1000)'
                ')')
    cur.execute('CREATE TABLE IF NOT EXISTS logs('
                'dttm DATE, '
                'platform VARCHAR(10), '
                'short VARCHAR(16)'
                ')')
    cur.execute('CREATE TABLE IF NOT EXISTS wamessage(message VARCHAR(1000))')


def get_shorten_url(length=6):
    if length > max_length:
        raise EnvironmentError(
            'desired length is greater than max length allowed'
        )
    chars = string.ascii_uppercase + string.ascii_lowercase + string.digits
    short = "".join([random.choice(chars) for _ in range(length)])
    return short


def generic_descr_from_url(long_url):
    split_by_slash = long_url.split('/')
    site = split_by_slash[2]
    nmbr = None
    if site == 'wa.me':
        nmbr = split_by_slash[3].split('?')[0]
    args = long_url.split('?')
    if not len(args) > 1:  # there are no arguments
        return nmbr, site
    text = args[1].split(',')
    if not len(text) > 1 or len(text[1]) > 25:
        return nmbr, site
    name = text[1].replace('%20', ' ').strip()
    return nmbr, f'{site} para {name}'


def save_on_db(long_url, short_url, nmbr, descr):
    existing = False
    with DBContext() as (con, cur, param_char):
        res = cur.execute(
            f'SELECT short FROM mappings WHERE nmbr={param_char}', [nmbr]
        )
        res = res or cur
        res = res.fetchall()
        if res:
            existing = True
            return existing, res[0][0]
        res = cur.execute(
            f'SELECT short FROM mappings WHERE long={param_char}', [long_url]
        )
        res = res or cur
        res = res.fetchall()
        if res:
            existing = True
            return existing, res[0][0]
        res = cur.execute(
            f'SELECT long FROM mappings WHERE short={param_char}', [short_url]
        )
        res = res or cur
        res = res.fetchall()
        while res:
            existing = True
            short_url = get_shorten_url()
            res = cur.execute(
                f'SELECT long FROM mappings WHERE short={param_char}',
                [short_url]
            )
            res = res or cur
            res = res.fetchall()
        n, d = generic_descr_from_url(long_url)
        nmbr = nmbr or n
        descr = descr or d
        cur.execute(
            'INSERT INTO mappings VALUES ('
            f'{param_char}, {param_char}, {param_char}, {param_char})',
            (long_url, short_url, nmbr, descr)
        )
    return existing, short_url


# @app.route('/static/<path:path>')
# def serve_static(path):
#     return send_from_directory('static', path)


@app.route(f'/{admin_site}/export', methods=['GET'])
def export():
    with DBContext() as (con, cur, param_char):
        maps = cur.execute(
            'SELECT * FROM mappings'
        )
        maps = maps or cur
        rows = maps.fetchall()
    with io.StringIO() as file:
        writer = csv.writer(file)
        writer.writerow(('long', 'short', 'nmbr', 'description'))
        for row in rows:
            writer.writerow(row)
        mem = io.BytesIO()
        mem.write(file.getvalue().encode(encoding='latin1'))
        mem.seek(0)
    return send_file(
        mem, as_attachment=True, download_name='mappings.csv',
        mimetype='text/csv'
    )


@app.route(f'/{admin_site}/clean', methods=['GET'])
def clean_logs():
    months = request.args.get("months", 12)
    today = datetime.now().date()
    clean_th = today - relativedelta(months=months)
    with DBContext() as (con, cur, param_char):
        cur.execute(f'DELETE FROM logs WHERE dttm<{param_char}', [clean_th])
    return f"logs older than {months} months erased"


@app.route(f'/{admin_site}/shorten', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        data = request.form or request.json
        long_url = data['long-url']
        descr = data.get('description')
        nmbr = data.get('nmbr')
        short_url = data.get('short-url', get_shorten_url())
        try:
            short_url = save_on_db(long_url, short_url, nmbr, descr)
        except (sqlite3.IntegrityError, psycopg.IntegrityError):
            return "Request Error", 400

        return render_template(
            'success.html', exists=short_url[0],
            short_url=(root_url or request.url_root) + short_url[1]
        )
    return render_template('index.html')


@app.route(f'/{admin_site}/wame', methods=['POST', 'GET'])
def shorten_wame():
    if request.method == 'POST':
        text = request.form.get('text', '')
        name = request.form.get('name', '')
        phone = request.form.get('phone', '').replace(' ', '')
        if len(phone) < 10:
            return 'Invalid phone', 400
        if len(phone) == 10:
            phone = '+52' + phone
        if text:
            with DBContext() as (con, cur, param_char):
                cur.execute('DELETE FROM wamessage')
                cur.execute(f'INSERT INTO wamessage VALUES ({param_char})',
                            [text])
            text = text.replace(' ', '%20')
            text = text.replace('<nombre>', name)
        link = f'https://wa.me/{phone}/?text={text}'
        try:
            exists, short_url = save_on_db(
                link, get_shorten_url(), phone, None
            )
        except (sqlite3.IntegrityError, psycopg.IntegrityError):
            return "Request Error", 400

        return render_template(
            'success.html', exists=exists,
            short_url=(root_url or request.url_root) + short_url
        )

    with DBContext() as (con, cur, param_char):
        res = cur.execute('SELECT message FROM wamessage')
        res = res or cur
        res = res.fetchall()
    if not res:
        res = ''
    else:
        res = res[0][0]

    return render_template('wame.html', text=res)


@app.route('/<short_url>')
def url_redirect(short_url):
    now = datetime.now()
    with DBContext() as (con, cur, param_char):
        res = cur.execute(
            f"SELECT long FROM mappings WHERE short={param_char}", [short_url]
        )
        res = res or cur
        res = res.fetchall()
        headers = "".join([a[1] for a in request.headers]).lower()
        platform = 'NA'
        for p in PLATFORMS:
            if p in headers:
                platform = p
                break
        cur.execute(
            "INSERT INTO logs VALUES ("
            f"{param_char}, {param_char}, {param_char})",
            [now, platform, short_url]
        )

    if len(res) == 1:
        return redirect(res[0][0].replace("\n", ""))
    return 'Not found', 404


@app.route('/<short_url>/edit', methods=['GET', 'POST'])
def edit(short_url):
    if request.method == 'POST':
        data = request.form or request.json
        new_url = data.get('url', '')
        descr = data.get('description', '')
        if not new_url:
            return 'Request error', 400
        with DBContext() as (con, cur, param_char):
            cur.execute(
                f'UPDATE mappings SET long={param_char}, descr={param_char} '
                f'WHERE short={param_char}',
                [new_url, descr, short_url]
            )
        return redirect(url_for('home'))

    with DBContext() as (con, cur, param_char):
        res = cur.execute(
            f"SELECT long, descr FROM mappings WHERE short={param_char}",
            [short_url]
        )
        res = res or cur
        res = res.fetchall()
    if len(res) != 1:
        return 'Not found', 404
    return render_template(
        'update.html', short_url=short_url, long_url=res[0][0], descr=res[0][1]
    )


@app.route('/<short_url>/delete', methods=['GET', 'POST'])
def delete(short_url):
    if request.method == 'POST':
        with DBContext() as (con, cur, param_char):
            cur.execute(
                f"DELETE FROM mappings WHERE short={param_char}", [short_url]
            )
        return redirect(url_for('home'))

    with DBContext() as (con, cur, param_char):
        res = cur.execute(
            f"SELECT long, descr FROM mappings WHERE short={param_char}",
            [short_url]
        )
        res = res or cur
        res = res.fetchall()
    if len(res) != 1:
        return 'Not found', 404
    return render_template(
        'delete.html', short_url=short_url, long_url=res[0][0], descr=res[0][1]
    )


@app.route('/<short_url>/stats')
def stats(short_url):
    date_gte = request.args.get("since", "")

    str_query = ('SELECT platform, count(*) AS count FROM logs '
                 'WHERE short={param_char}')
    params = [short_url]
    if date_gte:
        str_query += ' AND date(dttm)>=date({param_char})'
        params.append(date_gte)
    str_query += ' GROUP BY platform'
    context = dict()
    platforms = dict()
    total_count = 0
    with DBContext() as (con, cur, param_char):
        query = cur.execute(
            f'SELECT long, descr FROM mappings WHERE short={param_char}',
            [short_url]
        )
        query = query or cur
        query = query.fetchall()
        res = cur.execute(str_query.format(param_char=param_char), params)
        res = res or cur
        for platform, count in res:
            platforms[platform] = count
            total_count += count

    if not query:
        return "Not Found", 404
    now = datetime.now().date()
    year = now.year
    month = str(now.month).zfill(2)
    dow = now.weekday()
    context['today'] = now.isoformat()
    context['week'] = f'{(now - timedelta(days=dow)).isoformat()}'
    context['month'] = f'{year}-{month}-01'
    context['year'] = f'{year}-01-01'
    context['long_url'] = query[0][0]
    context['descr'] = query[0][1]
    context['short_url'] = short_url
    context['platforms'] = platforms
    context['total_count'] = total_count
    return render_template('stats.html', **context)


if __name__ == "__main__":
    app.run(port=port)
