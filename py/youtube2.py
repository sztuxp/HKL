#coding=utf-8
#!/usr/bin/python
import re
import os
import sys
import json
import html
import time
from urllib.parse import quote, unquote, parse_qs, urlencode, urlparse, urlunparse

import requests
from base.spider import Spider

sys.path.append('..')

DEBUG_LOG = '/sdcard/Download/0712youtube_trace.log'

# ==================== 在这里配置你固定的播放列表（对应为大类分类） ====================
# type_id 填写播放列表的 playlist_id (即 list= 后面的参数)
# type_name 填写你想要显示的分类名称
YOUTUBE_CLASSES = [
    {'type_id': 'PLtKJNVcMbjLQ_M-a0ZjniEdFJ3yXrem3x', 'type_name': '2026'},
    {'type_id': 'PLtKJNVcMbjLTtSL1IudnX_XS9ywElex_E', 'type_name': '2025'},
    {'type_id': 'PLtKJNVcMbjLTNWAq-P0vZt-Rm7JYpGQdq', 'type_name': '2024'},
    {'type_id': 'PLtKJNVcMbjLQBej9ZrtDttmeM-ZuENQ3m', 'type_name': '2023'},
    {'type_id': 'PLtKJNVcMbjLSdXJ_XkiYsVZtz8QA7j7Yh', 'type_name': '2022'},
    {'type_id': 'PLtKJNVcMbjLSsnRb9ZONGFUh0nNzuIQxZ', 'type_name': '2021'},
    {'type_id': 'PLtKJNVcMbjLSSYUwY9mFUmr99MTl5AAGu', 'type_name': '2020'},
    {'type_id': 'PLtKJNVcMbjLQKBubz6HoKH3FWKeoh4qh_', 'type_name': '2019'},
    {'type_id': 'PLtKJNVcMbjLTA82NlL3yi3cCKY63C10_-', 'type_name': '2018'},
    {'type_id': 'PLtKJNVcMbjLT4EbtkW9OhjzxaNwTbKc55', 'type_name': '2017'},
    {'type_id': 'PLtKJNVcMbjLSvBQe3cK-LHutsR8SG5dpN', 'type_name': '2016'},
    {'type_id': 'PLtKJNVcMbjLTe8z2mBAU18X_I0JEy4GLQ', 'type_name': '2015'},
    {'type_id': 'PLtKJNVcMbjLQvVzsDomQLWqE8-uKDYRoY', 'type_name': '2014'},    
    {'type_id': 'PLtKJNVcMbjLRdCXW-QogELgq2CADSpIx5', 'type_name': '2013'},
    {'type_id': 'PLtKJNVcMbjLS73iuYapCc-6ZW47qzNatD', 'type_name': '2012'},
    {'type_id': 'PLtKJNVcMbjLQAfhPFHzJBazSjDYF7USoq', 'type_name': '2011'},
    {'type_id': 'PLtKJNVcMbjLSOM_50dx3UDRChgIYjU6Ne', 'type_name': '2010'},
]
# ====================================================================

def debug_log(message, data=None):
    try:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        if data is not None:
            if isinstance(data, (dict, list)):
                line += ' ' + json.dumps(data, ensure_ascii=False, default=str)
            else:
                line += ' ' + str(data)
        with open(DEBUG_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


class YouTubeLite:
    def __init__(self, session, headers=None, config=None):
        self.session = session
        self.headers = headers or {}
        self.config = config or {}
        self.player_cache = {}
        self.extract_cache = {}
        self.sig_plan_cache = {}
        self.extract_cache_ttl = int(self.config.get('extract_cache_ttl') or 300)

    def extract(self, url_or_id):
        video_id = self.extract_video_id(url_or_id)
        cached = self.extract_cache.get(video_id)
        now = time.time()
        if cached and cached.get('expires', 0) > now:
            debug_log('extract cache hit', {'video_id': video_id, 'ttl': int(cached.get('expires', 0) - now)})
            return cached.get('data')
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        extract_started = time.time()
        debug_log('extract start', {'input': url_or_id, 'video_id': video_id})
        watch_started = time.time()
        page_resp = self._get(watch_url)
        page = page_resp.text
        debug_log('watch page', {'status': page_resp.status_code, 'length': len(page), 'cost_ms': int((time.time() - watch_started) * 1000)})
        ytcfg = self._extract_ytcfg(page) or {}
        player_response = self._extract_initial_player_response(page) or {}
        player_url = self._extract_player_url(page)
        api_key = ytcfg.get('INNERTUBE_API_KEY') or self._search(r'"INNERTUBE_API_KEY":"([^"]+)"', page)
        visitor_data = self._extract_visitor_data(ytcfg, player_response)
        sts = None
        debug_log('page parsed', {'has_ytcfg': bool(ytcfg), 'has_initial_pr': bool(player_response), 'initial_status': (player_response.get('playabilityStatus') or {}).get('status'), 'initial_has_streaming': bool(player_response.get('streamingData')), 'has_api_key': bool(api_key), 'has_visitor': bool(visitor_data), 'sts': sts, 'player_url': player_url})
        context = ytcfg.get('INNERTUBE_CONTEXT') or {
            'client': {'clientName': 'WEB', 'clientVersion': '2.20240310.01.00', 'hl': 'en', 'gl': 'US'}
        }
        responses = [player_response] if player_response else []
        if api_key:
            api_responses = self._call_player_api(video_id, api_key, context, watch_url, visitor_data, sts)
            if not isinstance(api_responses, list):
                api_responses = [api_responses] if api_responses else []
            responses.extend([x for x in api_responses if x])
            debug_log('player api result', {'responses': len(api_responses), 'has_streaming': [bool((x or {}).get('streamingData')) for x in api_responses]})
        player_response = next((x for x in responses if (x.get('playabilityStatus') or {}).get('status') == 'OK'), player_response)
        status = (player_response.get('playabilityStatus') or {}).get('status')
        streaming = player_response.get('streamingData') or {}
        if status and status not in ('OK', 'LIVE_STREAM_OFFLINE') and not streaming:
            reason = (player_response.get('playabilityStatus') or {}).get('reason') or status
            raise Exception(f'YouTube 不可播放: {reason}')
        details = player_response.get('videoDetails') or {}
        raw_formats = []
        seen_raw = set()
        source_counts = []
        for response in responses:
            response_streaming = (response or {}).get('streamingData') or {}
            source_raw = (response_streaming.get('formats') or []) + (response_streaming.get('adaptiveFormats') or [])
            source_counts.append({'formats': len(response_streaming.get('formats') or []), 'adaptive': len(response_streaming.get('adaptiveFormats') or [])})
            for raw in source_raw:
                key = (raw.get('itag'), raw.get('url') or raw.get('signatureCipher') or raw.get('cipher') or raw.get('mimeType'))
                if key not in seen_raw:
                    seen_raw.add(key)
                    raw = raw.copy()
                    raw['_client_name'] = (response or {}).get('_client_name')
                    raw['_client_ua'] = (response or {}).get('_client_ua')
                    raw_formats.append(raw)
        debug_log('raw formats', {'sources': source_counts, 'total': len(raw_formats), 'sample_keys': sorted(list(raw_formats[0].keys())) if raw_formats else []})
        formats = []
        cipher_count = 0
        for raw in raw_formats:
            if raw.get('signatureCipher') or raw.get('cipher'):
                cipher_count += 1
            item = self._normalize_format(raw, player_url)
            if item and item.get('url'):
                formats.append(item)
        debug_log('normalized formats', {'count': len(formats), 'cipher_count': cipher_count, 'progressive': len([x for x in formats if x.get('vcodec') != 'none' and x.get('acodec') != 'none'])})
        if not formats:
            raise Exception('未获取到可用播放地址')
        data = {
            'id': video_id,
            'title': details.get('title') or video_id,
            'duration': int(details.get('lengthSeconds') or 0),
            'formats': formats,
        }
        self.extract_cache[video_id] = {'data': data, 'expires': time.time() + self.extract_cache_ttl}
        debug_log('extract complete', {'video_id': video_id, 'cost_ms': int((time.time() - extract_started) * 1000), 'formats': len(formats)})
        return data

    @staticmethod
    def extract_video_id(text):
        text = str(text or '').strip()
        for pattern in [
            r'(?:v=|/v/|/embed/|/shorts/|youtu\.be/)([0-9A-Za-z_-]{11})',
            r'^([0-9A-Za-z_-]{11})$',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        raise Exception('无法识别 YouTube 视频 ID')

    def _client_name_id(self, client_name):
        return {
            'WEB': 1,
            'MWEB': 2,
            'ANDROID': 3,
            'IOS': 5,
            'TVHTML5': 7,
            'ANDROID_VR': 28,
            'WEB_EMBEDDED_PLAYER': 56,
            'WEB_REMIX': 67,
        }.get(client_name, 1)

    def _extract_visitor_data(self, ytcfg, player_response):
        return (
            self.config.get('visitor_data')
            or ytcfg.get('VISITOR_DATA')
            or (((ytcfg.get('INNERTUBE_CONTEXT') or {}).get('client') or {}).get('visitorData'))
            or ((player_response.get('responseContext') or {}).get('visitorData'))
        )

    def _extract_signature_timestamp(self, video_id, player_url, ytcfg=None):
        try:
            code = self._get_player_code(player_url)
            sts = self._search(r'(?:signatureTimestamp|sts)\s*:\s*(\d{5})', code)
            return int(sts) if sts else None
        except Exception as e:
            debug_log('sts extract error', repr(e))
            return None

    def _get_po_token(self, client_name, context='gvs'):
        tokens = self.config.get('po_token') or self.config.get('po_tokens') or {}
        if isinstance(tokens, str):
            return tokens
        if isinstance(tokens, dict):
            return tokens.get(f'{client_name}.{context}') or tokens.get(client_name) or tokens.get(context)
        return None

    def choose_playable(self, formats, quality=None):
        all_videos = [x for x in formats if x.get('vcodec') != 'none' and x.get('acodec') == 'none']
        # candidates = all_videos[:]
        
        # 强制仅筛选高度小于等于 720P 的画质选项
        candidates = [x for x in all_videos if int(x.get('height') or 0) <= 720]
        
        if quality == '4k':
            candidates = [x for x in candidates if int(x.get('height') or 0) >= 2160]
        elif quality == '2k':
            candidates = [x for x in candidates if 1440 <= int(x.get('height') or 0) < 2160]
        elif quality == '1080p':
            candidates = [x for x in candidates if 1000 <= int(x.get('height') or 0) < 1440]
        elif quality == 'best':
            safe_candidates = [x for x in candidates if not self._is_risky_best_video(x)]
            if safe_candidates:
                candidates = safe_candidates
        else:
            candidates = [x for x in candidates if int(x.get('height') or 0) >= 1080]
        if not candidates and quality == 'best':
            candidates = all_videos
        if not candidates:
            return None
        candidates.sort(key=lambda x: (
            self._video_codec_priority(x),
            int(x.get('height') or 0),
            int(x.get('bitrate') or 0)
        ), reverse=True)
        selected = candidates[0]
        debug_log('video selected fast', {
            'quality': quality,
            'itag': selected.get('itag'),
            'height': selected.get('height'),
            'mime': selected.get('mimeType'),
            'codec_priority': self._video_codec_priority(selected),
            'candidates': len(candidates),
            'probe_skipped': True,
        })
        return selected

    def _video_codec_priority(self, item):
        mime = (item.get('mimeType') or '').lower()
        codecs = (item.get('codecs') or '').lower()
        if 'vp9.2' in mime or 'vp09.02' in codecs:
            return 4
        if 'vp9' in mime or 'vp09' in codecs:
            return 3
        if 'avc' in codecs or 'h264' in codecs:
            return 2
        if 'av01' in codecs:
            return 1
        return 0

    def _is_risky_best_video(self, item):
        codecs = (item.get('codecs') or '').lower()
        return 'av01' in codecs

    def choose_video_tracks(self, formats, quality=None):
        videos = [x for x in formats if x.get('vcodec') != 'none' and x.get('acodec') == 'none']
        # cap = 2160 if quality in ('best', '4k') else 1440 if quality == '2k' else 1080
        
        # 将最高画质上限设定为 720P
        cap = 720
        
        videos = [x for x in videos if int(x.get('height') or 0) <= cap] or videos
        vp9 = [x for x in videos if self._video_codec_priority(x) >= 3]
        if vp9:
            videos = vp9
        sdr = [x for x in videos if not self._is_hdr_video(x)]
        hdr = [x for x in videos if self._is_hdr_video(x)]
        sort_key = lambda x: (int(x.get('height') or 0), int(x.get('bitrate') or 0))
        sdr.sort(key=sort_key, reverse=True)
        hdr.sort(key=sort_key, reverse=True)
        tracks = []
        if sdr:
            item = sdr[0].copy()
            item['track_name'] = 'SDR'
            item['is_hdr'] = False
            tracks.append(item)
        if hdr:
            item = hdr[0].copy()
            item['track_name'] = 'HDR'
            item['is_hdr'] = True
            tracks.append(item)
        if not tracks:
            item = self.choose_playable(formats, quality)
            if item:
                item = item.copy()
                item['track_name'] = 'HDR' if self._is_hdr_video(item) else 'SDR'
                item['is_hdr'] = self._is_hdr_video(item)
                tracks.append(item)
        debug_log('video tracks selected', [{'name': x.get('track_name'), 'itag': x.get('itag'), 'height': x.get('height'), 'codecs': x.get('codecs')} for x in tracks])
        return tracks

    def _is_hdr_video(self, item):
        mime = (item.get('mimeType') or '').lower()
        codecs = (item.get('codecs') or '').lower()
        color = item.get('colorInfo') or {}
        return 'vp9.2' in mime or 'vp09.02' in codecs or bool(color.get('hdrMetadataInfo'))

    def choose_audio(self, formats):
        candidates = [x for x in formats if x.get('acodec') != 'none' and x.get('vcodec') == 'none']
        if not candidates:
            return None
        candidates.sort(key=lambda x: (1 if x.get('ext') == 'mp4' else 0, int(x.get('bitrate') or 0)), reverse=True)
        selected = candidates[0]
        debug_log('audio selected fast', {
            'itag': selected.get('itag'),
            'mime': selected.get('mimeType'),
            'bitrate': selected.get('bitrate'),
            'probe_skipped': True,
        })
        return selected

    def _probe_format(self, item):
        try:
            headers = self.headers.copy()
            headers.update(item.get('headers') or {})
            headers['Range'] = 'bytes=0-1'
            r = self.session.get(item.get('url'), headers=headers, stream=True, timeout=10)
            if r.url and r.url != item.get('url'):
                item['url'] = r.url
                item['redirected'] = True
                debug_log('probe redirected url', self._url_summary(r.url))
            status_code = r.status_code
            r.close()
            return status_code in (200, 206), status_code
        except Exception as e:
            return False, repr(e)

    def choose_best_video_audio(self, formats):
        videos = [x for x in formats if x.get('vcodec') != 'none' and x.get('acodec') == 'none']
        audios = [x for x in formats if x.get('acodec') != 'none' and x.get('vcodec') == 'none']
        videos.sort(key=lambda x: (int(x.get('height') or 0), int(x.get('bitrate') or 0)), reverse=True)
        audios.sort(key=lambda x: int(x.get('bitrate') or 0), reverse=True)
        return (videos[0] if videos else None), (audios[0] if audios else None)

    def _url_summary(self, media_url):
        parsed = urlparse(media_url or '')
        query = parse_qs(parsed.query)
        keys = ['itag', 'mime', 'c', 'expire', 'ip', 'mip', 'source', 'requiressl', 'gir', 'clen', 'dur', 'n', 'pot', 'sig', 'lsig', 'cms_redirect']
        return {
            'host': parsed.netloc,
            'path': parsed.path,
            'len': len(media_url or ''),
            'params': {k: bool(query.get(k)) if k in ('pot', 'sig', 'lsig', 'cms_redirect') else (query.get(k, [''])[0][:80]) for k in keys if k in query}
        }

    def _get(self, url, **kwargs):
        headers = self.headers.copy()
        headers.update(kwargs.pop('headers', {}) or {})
        r = self.session.get(url, headers=headers, timeout=kwargs.pop('timeout', 15), **kwargs)
        r.raise_for_status()
        return r

    def _post_json(self, url, payload, headers=None):
        h = self.headers.copy()
        h.update({'Content-Type': 'application/json', 'Origin': 'https://www.youtube.com'})
        if headers:
            h.update({k: v for k, v in headers.items() if v})
        r = self.session.post(url, json=payload, headers=h, timeout=15)
        r.raise_for_status()
        return r.json()

    def _call_player_api(self, video_id, api_key, context, referer, visitor_data=None, sts=None):
        clients = [
            {'client': {'clientName': 'ANDROID_VR', 'clientVersion': '1.65.10', 'deviceMake': 'Oculus', 'deviceModel': 'Quest 3', 'androidSdkVersion': 32, 'userAgent': 'com.google.android.apps.youtube.vr.oculus/1.65.10 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip', 'osName': 'Android', 'osVersion': '12L', 'hl': 'en', 'gl': 'US'}},
            {'client': {'clientName': 'ANDROID', 'clientVersion': '21.02.35', 'androidSdkVersion': 30, 'userAgent': 'com.google.android.youtube/21.02.35 (Linux; U; Android 11) gzip', 'osName': 'Android', 'osVersion': '11', 'hl': 'en', 'gl': 'US'}},
            {'client': {'clientName': 'IOS', 'clientVersion': '21.02.3', 'deviceMake': 'Apple', 'deviceModel': 'iPhone16,2', 'userAgent': 'com.google.ios.youtube/21.02.3 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)', 'osName': 'iPhone', 'osVersion': '18.3.2.22D82', 'hl': 'en', 'gl': 'US'}},
            context,
            {'client': {'clientName': 'MWEB', 'clientVersion': '2.20260115.01.00', 'userAgent': 'Mozilla/5.0 (iPad; CPU OS 16_7_10 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1,gzip(gfe)', 'hl': 'en', 'gl': 'US'}},
        ]
        results = []
        fallback = None
        for ctx in clients:
            client_name = (ctx.get('client') or {}).get('clientName')
            try:
                url = f'https://www.youtube.com/youtubei/v1/player?key={api_key}&prettyPrint=false'
                payload = {
                    'context': ctx,
                    'videoId': video_id,
                    'playbackContext': {'contentPlaybackContext': {'html5Preference': 'HTML5_PREF_WANTS', **({'signatureTimestamp': sts} if sts else {})}},
                    'contentCheckOk': True,
                    'racyCheckOk': True,
                }
                client = ctx.get('client') or {}
                headers = {
                    'Referer': referer,
                    'X-YouTube-Client-Name': str(self._client_name_id(client.get('clientName'))),
                    'X-YouTube-Client-Version': client.get('clientVersion') or '',
                }
                if visitor_data:
                    headers['X-Goog-Visitor-Id'] = visitor_data
                client_ua = client.get('userAgent')
                if client_ua:
                    headers['User-Agent'] = client_ua
                data = self._post_json(url, payload, headers=headers)
                status = (data.get('playabilityStatus') or {}).get('status')
                streaming = data.get('streamingData') or {}
                formats = streaming.get('formats') or []
                adaptive = streaming.get('adaptiveFormats') or []
                direct_video = [x for x in adaptive if (x.get('url') or x.get('signatureCipher') or x.get('cipher')) and str(x.get('mimeType') or '').startswith('video/')]
                direct_any = [x for x in formats + adaptive if x.get('url') or x.get('signatureCipher') or x.get('cipher')]
                has_streaming = bool(streaming)
                debug_log('player api client', {'client': client_name, 'status': status, 'has_streaming': has_streaming, 'formats': len(formats), 'adaptive': len(adaptive), 'direct_any': len(direct_any), 'direct_video': len(direct_video)})
                if has_streaming:
                    data['_client_name'] = client_name
                    data['_client_ua'] = client_ua
                    results.append(data)
                    # VR 明文格式最完整，成功后立即返回，避免再串行请求 4 个客户端。
                    if client_name == 'ANDROID_VR' and direct_video:
                        debug_log('player api fast return', {'client': client_name, 'direct_video': len(direct_video)})
                        return results
                if has_streaming and fallback is None:
                    fallback = data
                elif fallback is None:
                    fallback = data
            except Exception as e:
                debug_log('player api client error', {'client': client_name, 'error': repr(e)})
                continue
        return results or ([fallback] if fallback else [])

    def _normalize_format(self, fmt, player_url):
        media_url = fmt.get('url')
        if not media_url:
            cipher = fmt.get('signatureCipher') or fmt.get('cipher')
            if cipher:
                media_url = self._decrypt_signature_cipher(cipher, player_url)
        if not media_url:
            return None
        media_url = self._decrypt_nsig(media_url, player_url)
        client_name = fmt.get('_client_name')
        po_token = self._get_po_token(client_name, 'gvs') if client_name else None
        if po_token:
            sep = '&' if '?' in media_url else '?'
            media_url = f'{media_url}{sep}pot={quote(po_token)}'
        mime = fmt.get('mimeType') or ''
        ext = 'mp4' if 'mp4' in mime else 'webm' if 'webm' in mime else 'unknown'
        codecs = self._search(r'codecs="([^"]+)"', mime) or ''
        has_audio = mime.startswith('audio/') or any(x in codecs for x in ('mp4a', 'opus', 'vorbis'))
        has_video = mime.startswith('video/') or any(x in codecs for x in ('avc', 'vp9', 'av01', 'h264'))
        headers = (fmt.get('http_headers') or {}).copy()
        if fmt.get('_client_ua'):
            headers['User-Agent'] = fmt.get('_client_ua')
        return {
            'itag': fmt.get('itag'),
            'url': media_url,
            'mimeType': mime,
            'client': fmt.get('_client_name'),
            'ext': ext,
            'width': fmt.get('width') or 0,
            'height': fmt.get('height') or 0,
            'fps': fmt.get('fps') or 0,
            'bitrate': fmt.get('bitrate') or fmt.get('averageBitrate') or 0,
            'contentLength': fmt.get('contentLength'),
            'initRange': fmt.get('initRange') or {},
            'indexRange': fmt.get('indexRange') or {},
            'codecs': codecs,
            'quality': fmt.get('qualityLabel') or fmt.get('quality'),
            'colorInfo': fmt.get('colorInfo') or {},
            'vcodec': codecs if has_video else 'none',
            'acodec': codecs if has_audio else 'none',
            'headers': headers,
        }

    def _decrypt_signature_cipher(self, cipher, player_url):
        data = parse_qs(cipher)
        media_url = unquote(data.get('url', [''])[0])
        sig = unquote(data.get('s', [''])[0])
        sp = data.get('sp', ['sig'])[0]
        if not media_url:
            return ''
        if sig:
            decoded = self._decrypt_sig(sig, player_url)
            debug_log('signature cipher', {'sp': sp, 'sig_len': len(sig), 'decoded_changed': decoded != sig, 'has_player': bool(player_url)})
            sep = '&' if '?' in media_url else '?'
            media_url = f'{media_url}{sep}{sp}={quote(decoded)}'
        return media_url

    def _decrypt_sig(self, sig, player_url):
        cache_key = player_url or ''
        if cache_key in self.sig_plan_cache:
            plan = self.sig_plan_cache.get(cache_key)
            debug_log('sig plan cache', {'has_plan': bool(plan), 'plan': plan[:8] if plan else None})
        else:
            code = self._get_player_code(player_url)
            plan = self._extract_sig_plan(code)
            self.sig_plan_cache[cache_key] = plan
            debug_log('sig plan', {'code_len': len(code), 'has_plan': bool(plan), 'plan': plan[:8] if plan else None})
        if not plan:
            return sig
        arr = list(sig)
        for op, arg in plan:
            if op == 'reverse':
                arr.reverse()
            elif op in ('slice', 'splice'):
                arr = arr[int(arg):]
            elif op == 'swap' and arr:
                j = int(arg) % len(arr)
                arr[0], arr[j] = arr[j], arr[0]
        return ''.join(arr)

    def _decrypt_nsig(self, media_url, player_url):
        try:
            parsed = urlparse(media_url)
            query = parse_qs(parsed.query)
            n_value = query.get('n', [None])[0]
            if not n_value:
                return media_url
            path_match = re.search(r'/n/([^/]+)', parsed.path)
            if path_match and path_match.group(1) != n_value:
                new_path = parsed.path.replace(f"/n/{path_match.group(1)}", f"/n/{n_value}", 1)
                fixed = urlunparse(parsed._replace(path=new_path))
                debug_log('n path synced', {'old': path_match.group(1), 'new_len': len(n_value), 'changed': fixed != media_url})
                return fixed
            debug_log('n present', {'n_len': len(n_value), 'has_path_n': bool(path_match)})
            return media_url
        except Exception as e:
            debug_log('n sync error', repr(e))
            return media_url

    def _get_player_code(self, player_url):
        if not player_url:
            return ''
        if player_url in self.player_cache:
            return self.player_cache[player_url]
        if player_url.startswith('//'):
            player_url = 'https:' + player_url
        elif player_url.startswith('/'):
            player_url = 'https://www.youtube.com' + player_url
        try:
            code = self._get(player_url).text
        except Exception:
            code = ''
        self.player_cache[player_url] = code
        return code

    def _extract_sig_plan(self, code):
        if not code:
            return None
        name = None
        for pattern in [
            r'\.sig\|\|([a-zA-Z0-9_$]+)\(',
            r'"signature",\s*([a-zA-Z0-9_$]+)\(',
            r'([a-zA-Z0-9_$]+)=function\(a\)\{a=a\.split\(""\);',
        ]:
            m = re.search(pattern, code)
            if m:
                name = m.group(1)
                break
        if not name:
            return None
        body = self._extract_js_function_body(code, name)
        if not body:
            return None
        helper = self._search(r'([a-zA-Z0-9_$]+)\.[a-zA-Z0-9_$]+\(a,\d+\)', body)
        helper_map = self._extract_helper_object(code, helper) if helper else {}
        plan = []
        for part in body.split(';'):
            if 'reverse()' in part:
                plan.append(('reverse', 0))
                continue
            m = re.search(r'\.slice\((\d+)\)', part)
            if m:
                plan.append(('slice', int(m.group(1))))
                continue
            m = re.search(r'\.splice\(0,(\d+)\)', part)
            if m:
                plan.append(('splice', int(m.group(1))))
                continue
            m = re.search(r'([a-zA-Z0-9_$]+)\.([a-zA-Z0-9_$]+)\(a,(\d+)\)', part)
            if m and m.group(1) == helper:
                op = helper_map.get(m.group(2))
                if op:
                    plan.append((op, int(m.group(3))))
        return plan or None

    def _extract_helper_object(self, code, name):
        if not name:
            return {}
        m = re.search(r'var\s+' + re.escape(name) + r'=\{(.+?)\};', code, re.S) or re.search(re.escape(name) + r'=\{(.+?)\};', code, re.S)
        if not m:
            return {}
        result = {}
        for method, body in re.findall(r'([a-zA-Z0-9_$]+):function\([a-z,]+\)\{(.*?)\}', m.group(1)):
            if '.reverse(' in body:
                result[method] = 'reverse'
            elif '.splice(' in body:
                result[method] = 'splice'
            elif '.slice(' in body:
                result[method] = 'slice'
            elif 'a[0]' in body and 'length' in body:
                result[method] = 'swap'
        return result

    def _extract_n_function(self, code):
        if not code:
            return None
        name = None
        for pattern in [
            r'\.get\("n"\)\)&&\(b=([a-zA-Z0-9_$]+)(?:\[(\d+)\])?\(b\)',
            r'\.get\("n"\)\)&&\(b=([a-zA-Z0-9_$]+)\(b\)',
            r'([a-zA-Z0-9_$]+)=function\(a\)\{var b=a\.split\(""\)',
            r'function\s+([a-zA-Z0-9_$]+)\(a\)\{var b=a\.split\(""\)',
            r'([a-zA-Z0-9_$]+)=function\(a\)\{a=a\.split\(""\)',
        ]:
            m = re.search(pattern, code)
            if m:
                name = m.group(1)
                break
        if not name:
            return None
        body = self._extract_js_function_body(code, name)
        debug_log('n function', {'name': name, 'body_len': len(body)})
        if not body:
            return None

        def transform(value):
            arr = list(value)
            for part in body.split(';'):
                if 'reverse()' in part:
                    arr.reverse()
                m = re.search(r'\.slice\((\d+)\)', part)
                if m:
                    arr = arr[int(m.group(1)):]
                m = re.search(r'\.splice\(0,(\d+)\)', part)
                if m:
                    arr = arr[int(m.group(1)):]
            return ''.join(arr) or value
        return transform

    def _extract_js_function_body(self, code, name):
        starts = []
        for pattern in [
            r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{',
            re.escape(name) + r'\s*=\s*function\s*\([^)]*\)\s*\{',
            r'var\s+' + re.escape(name) + r'\s*=\s*function\s*\([^)]*\)\s*\{',
        ]:
            m = re.search(pattern, code)
            if m:
                starts.append(m.end() - 1)
        if not starts:
            return ''
        start = starts[0]
        depth = 0
        in_str = None
        escape = False
        for i in range(start, len(code)):
            ch = code[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if in_str:
                if ch == in_str:
                    in_str = None
                continue
            if ch in ('"', "'", '`'):
                in_str = ch
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return code[start + 1:i]
        return ''

    def _extract_ytcfg(self, text):
        m = re.search(r'ytcfg\.set\s*\(\s*({.+?})\s*\)\s*;', text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except Exception:
            return None

    def _extract_initial_player_response(self, text):
        return self._extract_json_after(text, 'ytInitialPlayerResponse')

    def _extract_json_after(self, text, marker):
        pos = text.find(marker)
        if pos < 0:
            return None
        start = text.find('{', pos)
        if start < 0:
            return None
        depth = 0
        in_str = None
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if in_str:
                if ch == in_str:
                    in_str = None
                continue
            if ch == '"':
                in_str = ch
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:
                        return None
        return None

    def _extract_player_url(self, text):
        for pattern in [
            r'"jsUrl":"([^"]+)"',
            r'"PLAYER_JS_URL":"([^"]+)"',
            r'(/s/player/[^"\\]+/base\.js)',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1).replace('\\/', '/')
        return ''

    @staticmethod
    def _search(pattern, text, default=None):
        m = re.search(pattern, text or '', re.S)
        return m.group(1) if m else default

class Spider(Spider):
    def getName(self):
        return 'YouTube视频'

    def init(self, extend):
        try:
            self.extendDict = json.loads(extend) if extend else {}
        except Exception:
            self.extendDict = {}
        self.session = requests.Session()
        self.proxy_str = None
        proxy_val = self.extendDict.get('proxy')
        if proxy_val:
            if isinstance(proxy_val, dict):
                self.session.proxies = proxy_val
                self.proxy_str = (proxy_val.get('http') or proxy_val.get('https') or '').replace('http://', '').replace('https://', '')
            elif isinstance(proxy_val, str):
                self.proxy_str = proxy_val.replace('http://', '').replace('https://', '')
                proxy_url = f'http://{self.proxy_str}'
                self.session.proxies = {'http': proxy_url, 'https': proxy_url}
        self.header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://www.youtube.com/'
        }
        self.session.headers.update(self.header)
        self.yt = YouTubeLite(self.session, self.header, self.extendDict)
        self.config = {}
        self.search_page_cache = {}

    def homeContent(self, filter):
        # 1. 过滤大类，直接加载我们写死的播放列表名称作为主分类
        result = {'class': YOUTUBE_CLASSES}
        return result

    def homeVideoContent(self):
        # 默认推荐直接展示第一个播放列表下的视频
        if YOUTUBE_CLASSES:
            return self.categoryContent(YOUTUBE_CLASSES[0]['type_id'], 1, False, {})
        return {'list': []}

    def categoryContent(self, cid, page, filter, ext):
        """核心改动：点击分类大类（即播放列表）时，直接解析该播放列表下的所有视频，并平铺展示出来"""
        playlist_id = str(cid or '').strip()
        videos = []
        seen_vids = set()
        
        playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
        try:
            r = self.session.get(playlist_url, timeout=10)
            html_str = r.text
            data = self.yt._extract_json_after(html_str, 'ytInitialData') or {}
            
            # 优先从首屏 JSON 数据中递归扫描所有的视频条目
            def scan_playlist(obj):
                if isinstance(obj, dict):
                    if 'playlistVideoRenderer' in obj:
                        item = obj['playlistVideoRenderer']
                        v_id = item.get('videoId')
                        if not v_id:
                            nav = item.get('navigationEndpoint', {})
                            v_id = nav.get('watchEndpoint', {}).get('videoId')
                            
                        t_obj = item.get('title') or {}
                        v_title = t_obj.get('simpleText') or ''.join([x.get('text', '') for x in t_obj.get('runs', [])]) or 'Video'
                        
                        if v_id and len(v_id) == 11 and v_id not in seen_vids:
                            seen_vids.add(v_id)
                            videos.append({
                                'vod_id': v_id,
                                'vod_name': html.unescape(v_title),
                                'vod_pic': f'https://img.youtube.com/vi/{v_id}/hqdefault.jpg',
                                'vod_remarks': '播放',
                            })
                            
                    elif 'gridVideoRenderer' in obj:
                        item = obj['gridVideoRenderer']
                        v_id = item.get('videoId')
                        t_obj = item.get('title') or {}
                        v_title = t_obj.get('simpleText') or ''.join([x.get('text', '') for x in t_obj.get('runs', [])]) or 'Video'
                        if v_id and len(v_id) == 11 and v_id not in seen_vids:
                            seen_vids.add(v_id)
                            videos.append({
                                'vod_id': v_id,
                                'vod_name': html.unescape(v_title),
                                'vod_pic': f'https://img.youtube.com/vi/{v_id}/hqdefault.jpg',
                                'vod_remarks': '播放',
                            })

                    for value in obj.values():
                        scan_playlist(value)
                elif isinstance(obj, list):
                    for value in obj:
                        scan_playlist(value)

            scan_playlist(data)
            
            # 正则强力突破懒加载限制：直接通过正则将页面缓存的所有视频 ID 提取出来追加
            blacklist_ids = {'default', 'hqdefault', 'mqdefault', 'sddefault', 'maxresdefa'}
            raw_matches = re.findall(r'/watch\?v=([0-9A-Za-z_-]{11})', html_str)
            raw_matches += re.findall(r'"videoId"\s*:\s*"([0-9A-Za-z_-]{11})"', html_str)
            
            match_index = len(videos) + 1
            for v_id in raw_matches:
                if v_id and v_id not in seen_vids and v_id not in blacklist_ids:
                    seen_vids.add(v_id)
                    videos.append({
                        'vod_id': v_id,
                        'vod_name': f"集数-第 {match_index} 期视频",
                        'vod_pic': f'https://img.youtube.com/vi/{v_id}/hqdefault.jpg',
                        'vod_remarks': '播放',
                    })
                    match_index += 1

            debug_log("parsed category playlist videos", {"id": playlist_id, "count": len(videos)})
        except Exception as e:
            debug_log("category playlist parse error", repr(e))

        return {
            'list': videos, 
            'page': 1, 
            'pagecount': 1, 
            'limit': len(videos), 
            'total': len(videos)
        }

    def searchContent(self, key, quick, pg=1):
        # 搜索框默认锁定，直接返回第一个列表内容防止报错
        if YOUTUBE_CLASSES:
            return self.categoryContent(YOUTUBE_CLASSES[0]['type_id'], 1, False, {})
        return {'list': []}

    def detailContent(self, did):
        # 点击视频卡片后，由于已经是单个视频，走原版的提取逻辑
        video_id = did[0]
        title = self._get_video_title(video_id)
        safe_title = self._safe_title(title)
        play_sources = []
        play_urls = []
        try:
            data = self.yt.extract(video_id)
            tracks = self.yt.choose_video_tracks(data.get('formats') or [], 'best')
            for track in tracks:
                height = int(track.get('height') or 0)
                kind = track.get('track_name') or ('HDR' if track.get('is_hdr') else 'SDR')
                name = f'{height}p {kind}' if height else kind
                quality = 'hdr' if kind == 'HDR' else 'best'
                play_sources.append(name)
                play_urls.append(f'{safe_title} {name}${video_id}@{quality}')
            debug_log('detail dynamic sources', {'video_id': video_id, 'sources': play_sources})
        except Exception as e:
            debug_log('detail dynamic sources error', {'video_id': video_id, 'error': repr(e)})
        if not play_sources:
            play_sources = ['SDR', 'HDR']
            play_urls = [
                f'{safe_title} SDR${video_id}@best',
                f'{safe_title} HDR${video_id}@hdr',
            ]
        vod = {
            'vod_id': video_id,
            'vod_name': title,
            'vod_pic': f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg',
            'vod_play_from': '$$$'.join(play_sources),
            'vod_play_url': '$$$'.join(play_urls)
        }
        return {'list': [vod]}

    def _build_direct_play_url(self, media_url, headers, ext):
        header_query = urlencode({k: v for k, v in (headers or {}).items() if v})
        return f'{media_url}|{header_query}' if header_query else media_url

    def playerContent(self, flag, pid, vipFlags):
        raw_pid = pid.split('$')[-1]
        if '@' in raw_pid:
            video_id, quality = raw_pid.rsplit('@', 1)
        else:
            video_id, quality = raw_pid, '1080p'
        if quality not in ('best', 'hdr', '4k', '2k', '1080p'):
            quality = 'best'
        debug_log('playerContent', {'flag': flag, 'pid': pid, 'video_id': video_id, 'quality': quality})
        try:
            data = self.yt.extract(video_id)
            all_tracks = self.yt.choose_video_tracks(data['formats'], 'best')
            wanted_name = 'HDR' if quality == 'hdr' else 'SDR'
            video_tracks = [x for x in all_tracks if x.get('track_name') == wanted_name]
            if not video_tracks and all_tracks:
                video_tracks = [all_tracks[0]]
            if video_tracks:
                audio = self.yt.choose_audio(data['formats'])
                debug_log('selected track', {'requested': wanted_name, 'track': {'name': video_tracks[0].get('track_name'), 'itag': video_tracks[0].get('itag'), 'height': video_tracks[0].get('height'), 'mime': video_tracks[0].get('mimeType')}, 'audio': audio.get('itag') if audio else None})
                if audio:
                    cache_key = f'yt_{video_id}_{quality}'
                    self.setCache(cache_key, {
                        'video_tracks': video_tracks,
                        'video_url': video_tracks[0]['url'],
                        'audio_url': audio['url'],
                        'video_item': video_tracks[0],
                        'audio_item': audio,
                        'duration': data.get('duration') or 0,
                        'expires': time.time() + 300,
                    })
                    return {'parse': 0, 'jx': 0, 'url': f'http://127.0.0.1:9978/proxy?do=py&type=mpd&vid={video_id}&quality={quality}', 'format': 'application/dash+xml'}
                playable = video_tracks[0]
                headers = self.header.copy()
                headers.update(playable.get('headers') or {})
                return {'parse': 0, 'jx': 0, 'url': playable['url'], 'header': headers}
            raise Exception(f'没有可直接播放的 {quality} 视频流格式')
        except Exception as e:
            debug_log('playerContent error', repr(e))
            print(f'[YouTubeLite] 解析失败: {e}')
            res = {'parse': 1, 'url': f'https://www.youtube.com/embed/{video_id}?autoplay=1', 'header': json.dumps(self.header)}
            if self.proxy_str:
                res['proxy'] = self.proxy_str
            return res

    def localProxy(self, params):
        if params.get('do') != 'py':
            return None
        if params.get('type') == 'mpd':
            return self._proxy_mpd(params)
        if params.get('type') == 'media':
            return self._proxy_media(params)
        if params.get('type') == 'single':
            return self._proxy_single(params)
        return None

    def _proxy_single(self, params):
        vid = params.get('vid')
        debug_log('proxy single request', {'vid': vid, 'range': params.get('range'), 'keys': sorted(list(params.keys()))[:20]})
        data = self.getCache(f'yt_single_{vid}') if vid else None
        if not data:
            return [404, 'text/plain', '播放缓存已过期或不存在']
        target_url = data.get('url')
        if not target_url:
            return [404, 'text/plain', '播放地址不存在']
        headers = (data.get('headers') or self.header).copy()
        range_header = params.get('range') or params.get('Range')
        if range_header:
            headers['Range'] = range_header
        try:
            r = self.session.get(target_url, headers=headers, stream=True, timeout=30)
            debug_log('proxy single response', {'status': r.status_code, 'content_type': r.headers.get('content-type'), 'content_length': r.headers.get('content-length'), 'content_range': r.headers.get('content-range')})
            content_type = r.headers.get('content-type', 'video/mp4')
            resp_headers = {
                'Content-Type': content_type,
                'Accept-Ranges': 'bytes',
                'Cache-Control': 'no-cache',
            }
            if r.headers.get('content-range'):
                resp_headers['Content-Range'] = r.headers.get('content-range')
            if r.headers.get('content-length'):
                resp_headers['Content-Length'] = r.headers.get('content-length')
            return [r.status_code, content_type, r.content, resp_headers]
        except Exception as e:
            debug_log('proxy single error', repr(e))
            return [500, 'text/plain', f'代理播放失败: {str(e)}']

    def _proxy_mpd(self, params):
        vid = params.get('vid')
        quality = params.get('quality') or '1080p'
        data = self.getCache(f'yt_{vid}_{quality}') if vid else None
        if not data:
            return [404, 'text/plain', '视频缓存已过期或不存在']
        audio_url = data.get('audio_url')
        duration = data.get('duration') or 0
        video_tracks = data.get('video_tracks') or [data.get('video_item') or {}]
        audio_item = data.get('audio_item') or {}
        media_base = f'http://127.0.0.1:9978/proxy?do=py&type=media&vid={vid}&quality={quality}'
        direct_segments = str(self.extendDict.get('seg') or 'proxy').lower() == 'direct'
        duration_pt = f"PT{int(duration or 0)}S"
        mpd = f'''<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="{duration_pt}" minBufferTime="PT1.5S" profiles="urn:mpeg:dash:profile:isoff-on-demand:2011">
  <Period id="1" start="PT0S">
'''
        for item in video_tracks:
            init_range = item.get('initRange') or {}
            index_range = item.get('indexRange') or {}
            name = item.get('track_name') or ('HDR' if item.get('is_hdr') else 'SDR')
            base_url = item.get('url') if direct_segments else media_base + f"&track=video&itag={item.get('itag')}"
            mpd += f'''    <AdaptationSet mimeType="{html.escape((item.get('mimeType') or 'video/webm').split(';')[0])}" startWithSAP="1" segmentAlignment="true" scanType="progressive">
      <Representation id="v{item.get('itag', 1)}" bandwidth="{item.get('bitrate', 1000000)}" codecs="{html.escape(item.get('codecs') or '')}" height="{item.get('height', 0)}" width="{item.get('width', 0)}">
        <BaseURL>{html.escape(base_url)}</BaseURL>
        <SegmentBase indexRange="{index_range.get('start', '0')}-{index_range.get('end', '0')}"><Initialization range="{init_range.get('start', '0')}-{init_range.get('end', '0')}"/></SegmentBase>
      </Representation>
    </AdaptationSet>
'''
        if audio_url:
            audio_init = audio_item.get('initRange') or {}
            audio_index = audio_item.get('indexRange') or {}
            audio_base = audio_url if direct_segments else media_base + '&track=audio'
            mpd += f'''    <AdaptationSet mimeType="{html.escape((audio_item.get('mimeType') or 'audio/mp4').split(';')[0])}" startWithSAP="1" segmentAlignment="true" lang="und">
      <Representation id="audio" bandwidth="{audio_item.get('bitrate', 128000)}" codecs="{html.escape(audio_item.get('codecs') or '')}" audioSamplingRate="44100">
        <BaseURL>{html.escape(audio_base)}</BaseURL>
        <SegmentBase indexRange="{audio_index.get('start', '0')}-{audio_index.get('end', '0')}"><Initialization range="{audio_init.get('start', '0')}-{audio_init.get('end', '0')}"/></SegmentBase>
      </Representation>
    </AdaptationSet>
'''
        mpd += '  </Period>\n</MPD>'
        debug_log('proxy mpd tracks', {'vid': vid, 'quality': quality, 'tracks': [{'name': x.get('track_name'), 'itag': x.get('itag')} for x in video_tracks], 'audio': audio_item.get('itag'), 'direct': direct_segments, 'duration': duration_pt})
        return [200, 'application/dash+xml', mpd]

    def _proxy_media(self, params):
        vid = params.get('vid')
        quality = params.get('quality') or '1080p'
        track = params.get('track')
        data = self.getCache(f'yt_{vid}_{quality}') if vid else None
        if not data or track not in ('video', 'audio'):
            return [404, 'text/plain', '媒体不存在']
        if track == 'video':
            wanted_itag = str(params.get('itag') or '')
            tracks = data.get('video_tracks') or [data.get('video_item') or {}]
            media_item = next((x for x in tracks if str(x.get('itag')) == wanted_itag), tracks[0] if tracks else {})
            target_url = media_item.get('url')
        else:
            media_item = data.get('audio_item') or {}
            target_url = data.get('audio_url') or media_item.get('url')
        if not target_url:
            return [404, 'text/plain', f'{track} 流不存在']
        headers = self.header.copy()
        headers.update((media_item or {}).get('headers') or {})
        range_header = params.get('range') or params.get('Range')
        if range_header:
            headers['Range'] = range_header
        try:
            r = self.session.get(target_url, headers=headers, stream=True, timeout=30)
            content_type = r.headers.get('content-type', 'application/octet-stream')
            debug_log('proxy media response', {'track': track, 'itag': media_item.get('itag'), 'track_name': media_item.get('track_name'), 'status': r.status_code, 'range': range_header, 'content_type': content_type, 'content_length': r.headers.get('content-length'), 'content_range': r.headers.get('content-range')})
            resp_headers = {'Content-Type': content_type, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-cache'}
            if r.headers.get('content-range'):
                resp_headers['Content-Range'] = r.headers.get('content-range')
            if r.headers.get('content-length'):
                resp_headers['Content-Length'] = r.headers.get('content-length')
            return [r.status_code, content_type, r.content, resp_headers]
        except Exception as e:
            return [500, 'text/plain', f'代理媒体失败: {str(e)}']

    def _normalize_category_id(self, cid):
        return cid

    def _normalize_filter_term(self, value):
        return ""

    def _build_category_keyword(self, cid, filters=None):
        return ""

    def _search_cache_key(self, key):
        return re.sub(r'\s+', ' ', str(key or '')).strip().lower()

    def _search_youtube(self, key):
        return []

    def _search_youtube_page(self, key, page=1):
        return [], False

    def _extract_videos_fixed(self, html_str, limit=30):
        return []

    def _extract_videos_from_api(self, data, limit=30):
        return []

    def _parse_renderer(self, renderer):
        return None

    def _get_video_title(self, vid):
        try:
            r = self.session.get(f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json', timeout=5)
            return r.json().get('title') or vid
        except Exception:
            return vid

    def _safe_title(self, title):
        if not title:
            return 'video'
        return re.sub(r'[#$@%&!?*|\\/:<>]', ' ', title)[:60]

    def _seconds_to_iso_duration(self, seconds):
        seconds = float(seconds or 0)
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds - hours * 3600 - minutes * 60
        parts = []
        if hours:
            parts.append(f'{hours}H')
        if minutes:
            parts.append(f'{minutes}M')
        parts.append(f'{secs:.3f}S')
        return 'PT' + ''.join(parts)

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass
