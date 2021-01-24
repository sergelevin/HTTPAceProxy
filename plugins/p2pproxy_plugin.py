# -*- coding: utf-8 -*-
"""
P2pProxy response simulator
Uses torrent-tv API for it's work

What is this plugin for?
 It repeats the behavior of p2pproxy to support programs written for using p2pproxy

 Some of examples for what you can use this plugin:
    Comfort TV++ widget
    Official TorrentTV widget for Smart TV
    Kodi p2pproxy pvr plugin
    etc...

!!! It requires some changes in aceconfig.py:
    set the httpport to 8081
"""
__author__ = 'miltador, Dorik1972'

import logging, zlib
from torrenttv_api import TorrentTvApi
from datetime import timedelta, datetime
from urllib3.packages.six.moves.urllib.parse import parse_qs, quote, unquote
from urllib3.packages.six.moves import range
from urllib3.packages.six import ensure_binary
from PlaylistGenerator import PlaylistGenerator
import config.p2pproxy as config

class P2pproxy(object):
    handlers = ('channels', 'channels.m3u', 'archive', 'xbmc.pvr', 'logobase')
    logger = logging.getLogger('plugin_p2pproxy')
    compress_method = { 'zlib': zlib.compressobj(9, zlib.DEFLATED, zlib.MAX_WBITS),
                        'deflate': zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS),
                        'gzip': zlib.compressobj(9, zlib.DEFLATED, zlib.MAX_WBITS | 16) }

    def __init__(self, AceConfig, AceProxy): pass

    def handle(self, connection):
        P2pproxy.logger.debug('Handling request')

        hostport = connection.headers['Host']
        self.params = parse_qs(connection.query)

        # /channels/ branch
        if connection.reqtype in ('channels', 'channels.m3u'):

            if connection.path.endswith('play'):  # /channels/play?id=[id]
                channel_id = self.params.get('id', [''])[0]

                if not channel_id:
                    # /channels/play?id=&_=[epoch timestamp] is Torrent-TV widget proxy check
                    # P2pProxy simply closes connection on this request sending Server header, so do we
                    if self.params.get('_', [''])[0]:
                        P2pproxy.logger.debug('Status check')
                        response_headers = {'Content-Type': 'text/plain;charset=utf-8', 'Server': 'P2pProxy/1.0.4.4 HTTPAceProxy',
                                            'Access-Control-Allow-Origin': '*', 'Connection': 'close'}
                        connection.send_response(200)
                        for k,v in response_headers.items(): connection.send_header(k,v)
                        connection.wfile.write('\r\n')
                        return
                    else:
                        connection.send_error(400, 'Bad request')  # Bad request

                try: stream_type, stream, translations_list = TorrentTvApi(config.email, config.password).stream_source(channel_id)
                except Exception as err:
                   connection.send_error(404, '%s' % repr(err), logging.ERROR)
                name=logo=''

                for channel in translations_list:
                    if channel.getAttribute('id') == channel_id:
                        name = channel.getAttribute('name')
                        logo = channel.getAttribute('logo')
                        if logo != '' and config.fullpathlogo: logo = config.logobase + logo
                        break

                if stream_type not in ('torrent', 'contentid'):
                    connection.send_error(404, 'Unknown stream type: %s' % stream_type, logging.ERROR)
                elif stream_type == 'torrent': connection.path = '/url/%s/%s.ts' % (quote(stream,''), name)
                elif stream_type == 'contentid': connection.path = '/content_id/%s/%s.ts' % (stream, name)

                connection.__dict__.update({'splittedpath': connection.path.split('/')})
                connection.__dict__.update({'channelName': name, 'channelIcon': logo, 'reqtype': connection.splittedpath[1].lower()})
                return

            # /channels/?filter=[filter]&group=[group]&type=m3u
            elif connection.reqtype == 'channels.m3u' or self.params.get('type', [''])[0] == 'm3u':

                param_group = self.params.get('group', [''])[0]
                if param_group and 'all' in param_group: param_group = None

                try: translations_list = TorrentTvApi(config.email, config.password).translations(self.params.get('filter', ['all'])[0])
                except Exception as err:
                   connection.send_error(404, '%s' % repr(err), logging.ERROR)

                playlistgen = PlaylistGenerator(m3uchanneltemplate=config.m3uchanneltemplate)
                P2pproxy.logger.debug('Generating requested m3u playlist')
                for channel in translations_list:
                    group_id = channel.getAttribute('group')
                    if param_group and not group_id in param_group.split(','): continue # filter channels by &group=1,2,5...

                    name = channel.getAttribute('name')
                    try:
                        group = TorrentTvApi.CATEGORIES[int(group_id)]
                    except KeyError:
                        group = 'Unknown category ' + str(group_id)
                    cid = channel.getAttribute('id')
                    logo = channel.getAttribute('logo')
                    if logo != '' and config.fullpathlogo: logo = config.logobase + logo

                    fields = {'name': name, 'id': cid, 'url': cid, 'group': group, 'logo': logo}
                    fields.update({'tvgid': config.tvgid.format(**fields) if channel.getAttribute('epg_id') != '0' else ''})
                    playlistgen.addItem(fields)

                P2pproxy.logger.debug('Exporting m3u playlist')
                exported = playlistgen.exportm3u(hostport=hostport, header=config.m3uheadertemplate, fmt=self.params.get('fmt', [''])[0])
                connection.send_response(200)
                connection.send_header('Content-Type', 'audio/mpegurl; charset=utf-8')
                try:
                     h = connection.headers.get('Accept-Encoding').split(',')[0]
                     exported = P2pproxy.compress_method[h].compress(exported) + P2pproxy.compress_method[h].flush()
                     connection.send_header('Content-Encoding', h)
                except: pass

                connection.send_header('Content-Length', len(exported))
                connection.end_headers()
                connection.wfile.write(exported)

            # /channels/?filter=[filter]
            else:
                try: translations_list = TorrentTvApi(config.email, config.password).translations(self.params.get('filter', ['all'])[0], True)
                except Exception as err:
                   connection.send_error(404, '%s' % repr(err), logging.ERROR)

                P2pproxy.logger.debug('Exporting m3u playlist')
                response_headers = {'Access-Control-Allow-Origin': '*', 'Connection': 'close',
                                    'Content-Type': 'text/xml;charset=utf-8', 'Content-Length': len(translations_list) }
                try:
                     h = connection.headers.get('Accept-Encoding').split(',')[0]
                     translations_list = P2pproxy.compress_method[h].compress(translations_list) + P2pproxy.compress_method[h].flush()
                     connection.send_header('Content-Encoding', h)
                except: pass
                response_headers['Content-Length'] = len(translations_list)
                connection.send_response(200)
                for k,v in response_headers.items(): connection.send_header(k,v)
                connection.end_headers()
                connection.wfile.write(translations_list)

        # same as /channels request
        elif connection.reqtype == 'xbmc.pvr' and connection.path.endswith('playlist'):
            connection.send_response(200)
            connection.send_header('Access-Control-Allow-Origin', '*')
            connection.send_header('Connection', 'close')
            connection.send_header('Content-Type', 'text/xml;charset=utf-8')

            try: translations_list = TorrentTvApi(config.email, config.password).translations('all', True)
            except Exception as err:
               connection.send_error(404, '%s' % repr(err), logging.ERROR)
            try:
                h = connection.headers.get('Accept-Encoding').split(',')[0]
                translations_list = P2pproxy.compress_method[h].compress(translations_list) + P2pproxy.compress_method[h].flush()
                connection.send_header('Content-Encoding', h)
            except: pass
            connection.send_header('Content-Length', len(translations_list))
            connection.end_headers()
            P2pproxy.logger.debug('Exporting m3u playlist')
            connection.wfile.write(translations_list)

        # /archive/ branch
        elif connection.reqtype == 'archive':
            if connection.path.endswith(('dates', 'dates.m3u')):  # /archive/dates.m3u
                d = datetime.now()
                delta = timedelta(days=1)
                playlistgen = PlaylistGenerator()
                hostport = connection.headers['Host']
                days = int(self.params.get('days', ['7'])[0])
                suffix = '&suffix=%s' % self.params.get('suffix')[0] if 'suffix' in self.params else ''
                for i in range(days):
                    dfmt = d.strftime('%d-%m-%Y')
                    url = 'http://%s/archive/playlist/?date=%s%s' % (hostport, dfmt, suffix)
                    playlistgen.addItem({'group': '', 'tvg': '', 'name': dfmt, 'url': url})
                    d -= delta
                exported = playlistgen.exportm3u(hostport=hostport, empty_header=True, parse_url=False, fmt=self.params.get('fmt', [''])[0])
                connection.send_response(200)
                connection.send_header('Content-Type', 'audio/mpegurl; charset=utf-8')
                try:
                     h = connection.headers.get('Accept-Encoding').split(',')[0]
                     exported = P2pproxy.compress_method[h].compress(exported) + P2pproxy.compress_method[h].flush()
                     connection.send_header('Content-Encoding', h)
                except: pass
                connection.send_header('Content-Length', len(exported))
                connection.end_headers()
                connection.wfile.write(exported)
                return

            elif connection.path.endswith(('playlist', 'playlist.m3u')):  # /archive/playlist.m3u
                dates = []

                if 'date' in self.params:
                    for d in self.params['date']:
                        dates.append(self.parse_date(d).strftime('%d-%m-%Y'))
                else:
                    d = datetime.now()
                    delta = timedelta(days=1)
                    days = int(self.params.get('days', ['7'])[0])
                    for i in range(days):
                        dates.append(d.strftime('%d-%m-%Y'))
                        d -= delta

                connection.send_response(200)
                connection.send_header('Content-Type', 'audio/mpegurl; charset=utf-8')

                try: channels_list = TorrentTvApi(config.email, config.password).archive_channels()
                except Exception as err:
                   connection.send_error(404, '%s' % repr(err), logging.ERROR)
                hostport = connection.headers['Host']
                playlistgen = PlaylistGenerator()
                suffix = '&suffix=%s' % self.params.get('suffix')[0] if 'suffix' in self.params else ''
                for channel in channels_list:
                        epg_id = channel.getAttribute('epg_id')
                        name = channel.getAttribute('name')
                        logo = channel.getAttribute('logo')
                        if logo != '' and config.fullpathlogo: logo = config.logobase + logo
                        for d in dates:
                            n = name + ' (' + d + ')' if len(dates) > 1 else name
                            url = 'http://%s/archive/?type=m3u&date=%s&channel_id=%s%s' % (hostport, d, epg_id, suffix)
                            playlistgen.addItem({'group': name, 'tvg': '', 'name': n, 'url': url, 'logo': logo})

                exported = playlistgen.exportm3u(hostport=hostport, empty_header=True, parse_url=False, fmt=self.params.get('fmt', [''])[0])
                try:
                    h = connection.headers.get('Accept-Encoding').split(',')[0]
                    exported = P2pproxy.compress_method[h].compress(exported) + P2pproxy.compress_method[h].flush()
                    connection.send_header('Content-Encoding', h)
                except: pass
                connection.send_header('Content-Length', len(exported))
                connection.end_headers()
                connection.wfile.write(exported)
                return

            elif connection.path.endswith('channels'):  # /archive/channels
                connection.send_response(200)
                connection.send_header('Access-Control-Allow-Origin', '*')
                connection.send_header('Connection', 'close')
                connection.send_header('Content-Type', 'text/xml;charset=utf-8')

                try: archive_channels = TorrentTvApi(config.email, config.password).archive_channels(True)
                except Exception as err:
                   connection.send_error(404, '%s' % repr(err), logging.ERROR)
                P2pproxy.logger.debug('Exporting m3u playlist')
                try:
                    h = connection.headers.get('Accept-Encoding').split(',')[0]
                    archive_channels = P2pproxy.compress_method[h].compress(archive_channels) + P2pproxy.compress_method[h].flush()
                    connection.send_header('Content-Encoding', h)
                except: pass
                connection.send_header('Content-Length', len(archive_channels))
                connection.end_headers()
                connection.wfile.write(archive_channels)
                return

            if connection.path.endswith('play'):  # /archive/play?id=[record_id]
                record_id = self.params.get('id', [''])[0]
                if not record_id:
                    connection.send_error(400, 'Bad request')  # Bad request

                try: stream_type, stream = TorrentTvApi(config.email, config.password).archive_stream_source(record_id)
                except Exception as err:
                   connection.send_error(404, '%s' % repr(err), logging.ERROR)

                if stream_type not in ('torrent', 'contentid'):
                    connection.send_error(404, 'Unknown stream type: %s' % stream_type, logging.ERROR)
                elif stream_type == 'torrent': connection.path = '/url/%s/stream.ts' % quote(stream,'')
                elif stream_type == 'contentid': connection.path = '/content_id/%s/stream.ts' % stream

                connection.__dict__.update({'splittedpath': connection.path.split('/')})
                connection.__dict__.update({'reqtype': connection.splittedpath[1].lower()})
                return

            # /archive/?type=m3u&date=[param_date]&channel_id=[param_channel]
            elif self.params.get('type', [''])[0] == 'm3u':

                playlistgen = PlaylistGenerator()
                param_channel = self.params.get('channel_id', [''])[0]
                d = self.get_date_param()

                if not param_channel:
                    try: channels_list = TorrentTvApi(config.email, config.password).archive_channels()
                    except Exception as err:
                       connection.send_error(404, '%s' % repr(err), logging.ERROR)

                    for channel in channels_list:
                            channel_id = channel.getAttribute('epg_id')
                            try:
                                try: records_list = TorrentTvApi(config.email, config.password).records(channel_id, d)
                                except Exception as err:
                                   connection.send_error(404, '%s' % repr(err), logging.ERROR)
                                channel_name = channel.getAttribute('name')
                                logo = channel.getAttribute('logo')
                                if logo != '' and config.fullpathlogo: logo = config.logobase + logo

                                for record in records_list:
                                    name = record.getAttribute('name')
                                    record_id = record.getAttribute('record_id')
                                    playlistgen.addItem({'group': channel_name, 'tvg': '',
                                                         'name': name, 'url': record_id, 'logo': logo})
                            except: P2pproxy.logger.debug('Failed to load archive for %s' % channel_id)

                else:
                    try:
                       records_list = TorrentTvApi(config.email, config.password).records(param_channel, d)
                       channels_list = TorrentTvApi(config.email, config.password).archive_channels()
                    except Exception as err:
                       connection.send_error(404, '%s' % repr(err), logging.ERROR)
                    P2pproxy.logger.debug('Generating archive m3u playlist')

                    for record in records_list:
                        record_id = record.getAttribute('record_id')
                        channel_id = record.getAttribute('epg_id')
                        name = record.getAttribute('name')
                        d = datetime.fromtimestamp(float(record.getAttribute('time'))).strftime('%H:%M')
                        n = '%s %s' % (d, name)
                        logo = ''
                        for channel in channels_list:
                            if channel.getAttribute('epg_id') == channel_id:
                                channel_name = channel.getAttribute('name')
                                logo = channel.getAttribute('logo')

                        if channel_name != '': name = '(' + channel_name + ') ' + name
                        if logo != '' and config.fullpathlogo: logo = config.logobase + logo

                        playlistgen.addItem({'group': channel_name, 'name': n, 'url': record_id, 'logo': logo, 'tvg': ''})

                P2pproxy.logger.debug('Exporting m3u playlist')
                exported = playlistgen.exportm3u(hostport=hostport, empty_header=True, archive=True, fmt=self.params.get('fmt', [''])[0])

                connection.send_response(200)
                connection.send_header('Content-Type', 'audio/mpegurl; charset=utf-8')
                try:
                     h = connection.headers.get('Accept-Encoding').split(',')[0]
                     exported = P2pproxy.compress_method[h].compress(exported) + P2pproxy.compress_method[h].flush()
                     connection.send_header('Content-Encoding', h)
                except: pass
                connection.send_header('Content-Length', len(exported))
                connection.end_headers()
                connection.wfile.write(exported)

            # /archive/?date=[param_date]&channel_id=[param_channel]
            else:
                param_date = self.params.get('date', [''])[0]
                if not param_date: d = datetime.now()
                else:
                    try: d = parse_date(param_date)
                    except: return
                param_channel = self.params.get('channel_id', [''])[0]
                if not param_channel:
                    connection.send_error(500, 'Got /archive/ request but no channel_id specified!', logging.ERROR)

                connection.send_response(200)
                connection.send_header('Access-Control-Allow-Origin', '*')
                connection.send_header('Connection', 'close')
                connection.send_header('Content-Type', 'text/xml;charset=utf-8')

                try: records_list = TorrentTvApi(config.email, config.password).records(param_channel, d.strftime('%d-%m-%Y'), True)
                except Exception as err:
                   connection.send_error(404, '%s' % repr(err), logging.ERROR)
                P2pproxy.logger.debug('Exporting m3u playlist')
                try:
                    h = connection.headers.get('Accept-Encoding').split(',')[0]
                    records_list = P2pproxy.compress_method[h].compress(records_list) + P2pproxy.compress_method[h].flush()
                    connection.send_header('Content-Encoding', h)
                except: pass
                connection.send_header('Content-Length', len(records_list))
                connection.end_headers()
                connection.wfile.write(records_list)

        # Used to generate logomap for the torrenttv plugin
        elif connection.reqtype == 'logobase':
           logomap={}
#           try:
#              import config.picons.torrenttv as picons
#              logomap = { k: v[v.rfind('/')+1:] for k, v in picons.logomap.items() if v is not None }
#           except: pass

           try: translations_list = TorrentTvApi(config.email, config.password).translations('all')
           except Exception as err:
              connection.send_error(404, '%s' % repr(err), logging.ERROR)
              return
           logomap.update({ channel.getAttribute('name'):channel.getAttribute('logo') for channel in translations_list })

#           import requests
#           url = 'http://hmxuku36whbypzxi.onion/trash/ttv-list/ttv_logo.json'
#           proxies = {'http': 'socks5h://192.168.2.1:9100', 'https': 'socks5h://192.168.2.1:9100'}
#           with requests.get(url, proxies=proxies, timeout=30) as r:
#              logomap.update(r.json())

           connection.send_response(200)
           if self.params.get('format', [''])[0] == 'json':
              from requests.compat import json
              exported = ensure_binary(json.dumps({k:config.logobase + v for k,v in logomap.items()}, indent=4, ensure_ascii=False))
              connection.send_header('Content-Type', 'application/json')
           else:
              exported = "logobase = '%s'\nlogomap = {\n" % config.logobase
              exported += ''.join("    u'%s': logobase + '%s',\n" % (name, logo) for name, logo in logomap.items())
              exported += '}\n'
              exported = ensure_binary(exported)
              connection.send_header('Content-Type', 'text/plain;charset=utf-8')
           try:
              h = connection.headers.get('Accept-Encoding').split(',')[0]
              exported = P2pproxy.compress_method[h].compress(exported) + P2pproxy.compress_method[h].flush()
              connection.send_header('Content-Encoding', h)
           except: pass
           connection.send_header('Content-Length', len(exported))
           connection.end_headers()
           connection.wfile.write(exported)
           P2pproxy.logger.debug('%s picon channels exported' % len(logomap))

    def get_date_param(self):
        d = self.params.get('date', [''])[0]
        return datetime.now() if not d else self.parse_date(d)

    def parse_date(self, d):
        try: return datetime.strptime(d, '%d-%m-%Y')
        except IndexError as e:
            P2pproxy.logger.error('date param is not correct!')
            raise e
