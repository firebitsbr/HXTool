#!/usr/bin/env python
# -*- coding: utf-8 -*-

from functools import wraps
import os
import uuid
import threading
import datetime
import re
import colorsys
import traceback

try:
	from flask import request, session, redirect, url_for
except ImportError:
	print("hxtool requires the 'Flask' module, please install it.")
	exit(1)

# pycryptodome imports
try:
	from Crypto.Cipher import AES
	from Crypto.Protocol.KDF import PBKDF2
	from Crypto.Hash import HMAC, SHA256
except ImportError:
	print("hxtool requires the 'pycryptodome' module, please install it.")
	exit(1)

import hxtool_logging
import hxtool_vars
from hx_lib import HXAPI

logger = hxtool_logging.getLogger(__name__)

def get_N_HexCol(N=5):
	HSV_tuples = [(x * 1.0 / N, 0.7, 0.7) for x in range(N)]
	hex_out = []
	for rgb in HSV_tuples:
		rgb = map(lambda x: int(x * 255), colorsys.hsv_to_rgb(*rgb))
		hex_out.append('#%02x%02x%02x' % tuple(rgb))
	return hex_out

def valid_session_required(f):
	@wraps(f)
	def is_session_valid(*args, **kwargs):
		ret = redirect(url_for('login', redirect_uri = request.full_path))	
		if (session and 'ht_user' in session and 'ht_api_object' in session):
			o = HXAPI.deserialize(session['ht_api_object'])
			h = hash(o)
			if o.restIsSessionValid():
				kwargs['hx_api_object'] = o
				ret = f(*args, **kwargs)
				session['ht_api_object'] = o.serialize()
				return ret	
			else:
				logger.warn("The HX API token for the current session has expired, redirecting to the login page.")
		return ret
	return is_session_valid
	
def validate_json(keys, j):
	for k in keys:
		if not k in j or not j[k]:
			return False	
	return True
		
def make_response_by_code(code):
	code_table = {200 : {'message' : 'OK'},
				400 : {'message' : 'Invalid request'},
				404 : {'message' : 'Object not found'}}
	return (json.dumps(code_table.get(code)), code)
	

"""
Generate a random byte string for use in encrypting the background processor credentails
"""
def crypt_generate_random(length):
	return os.urandom(length)

"""
Return a PBKDF2 HMACSHA256 digest of a salt and password
"""
def crypt_pbkdf2_hmacsha256(salt, data):
	return PBKDF2(data, salt, dkLen = 32, count = 20000, prf = lambda p, s: HMAC.new(p, s, SHA256).digest())

"""
AES-256 operation
"""
def crypt_aes(key, iv, data, decrypt = False, base64_coding = True):
	cipher = AES.new(key, AES.MODE_OFB, iv)
	if decrypt:
		if base64_coding:
			data = HXAPI.b64(data, True)
		data = cipher.decrypt(data).decode('utf-8')
		# Implement PKCS7 de-padding
		pad_length = ord(data[-1:])
		if 1 <= pad_length <= 15:
			if all(c == chr(pad_length) for c in data[-pad_length:]):
				data = data[:len(data) - pad_length:]
		return data
	else:
		# Implement PKCS7 padding
		pad_length = 16 - (len(data) % 16)
		if pad_length < 16:
			data += (chr(pad_length) * pad_length)
		data = data.encode('utf-8')			
		data = cipher.encrypt(data)
		if base64_coding:
			data = HXAPI.b64(data)
		return data
	
"""
Iter over a Requests response object
and yield the chunk
"""
def iter_chunk(r, chunk_size = 1024):
	for chunk in r.iter_content(chunk_size = chunk_size):
		yield chunk

def download_directory_base():
	# TODO: check configuration, if none, return the default
	return "bulkdownload"
		
def combine_app_path(path, *paths):
	if not os.path.isabs(path):
		return os.path.join(hxtool_vars.app_instance_path, path, *paths)
	else:
		return path
		
def get_download_filename(host_name, host_id):
	return '{0}_{1}.zip'.format(host_name, host_id)

def make_download_directory(hx_host, download_id, job_type=None):
	download_directory = combine_app_path(download_directory_base(), hx_host, str(download_id))
	if job_type:
		download_directory = combine_app_path(download_directory_base(), hx_host, job_type, str(download_id))
	if not os.path.exists(download_directory):
		try:
			os.makedirs(download_directory)
		except:
			if not os.path.exists(download_directory): raise
			
	return download_directory

def secure_uuid4():
	return uuid.UUID(bytes=crypt_generate_random(16), version=4)

def format_activity_log(**kwargs):
	mystring = "ACTIVITY:"
	for key, value in kwargs.items():
		mystring += " " + key + "='" + HXAPI.compat_str(value) + "'"
	return(mystring)
	
# Workaround https://bugs.python.org/issue19377 on older Python versions		
def set_svg_mimetype():
	import mimetypes
	if not '.svg' in mimetypes.types_map:
		mimetypes.add_type('image/svg+xml', '.svg')
				
def set_time_macros(s):
	(s, n) = re.subn('--\#\{(now|\-(\d{1,5})(m|h))\}--', _time_replace, s, re.I) 
	return s, n > 0
	
def _time_replace(m):
	if m:
		now_time = datetime.datetime.utcnow()
		r = None
		
		if m.group(1).lower() == 'now':
			r = now_time
		elif m.group(3).lower() == 'm':
			r = now_time - datetime.timedelta(minutes = int(m.group(2)))
		elif m.group(3).lower() == 'h':
			r = now_time - datetime.timedelta(hours = int(m.group(2)))
		return HXAPI.hx_strftime(r)
	return None

def pretty_exceptions(e):
	return "{} in {}".format(e, traceback.format_exc())
	
class TemporaryFileLock(object):
	def __init__(self, file_path, file_name = 'lock_file'):
		self.file_name = os.path.join(file_path, file_name)
		self._stop_event = threading.Event()
		self.file_handle = None
	
	def acquire(self):
		while not self._stop_event.is_set():
			if not os.path.isfile(self.file_name):
				break
			self._stop_event.wait(1)
		self.file_handle = open(self.file_name, 'w')
		
	def release(self):
		self._stop_event.set()
		if self.file_handle:
			self.file_handle.close()
			os.remove(self.file_name)
	
	def __enter__(self):
		self.acquire()
		return self
		
	def __exit__(self, exc_type, exc_value, traceback):
		self.release()	
	
#from hxtool_scheduler import hxtool_scheduler_task
from hxtool_task_modules import *

def submit_bulk_job(hx_api_object, script_xml, hostset_id = None, hosts = {}, hxtool_host_list_id = None, start_time = None, schedule = None, comment = "HXTool Bulk Acquisition", download = True, task_profile = None, skip_base64 = False):
	bulk_download_eid = None
	
	bulk_acquisition_task = hxtool_scheduler_task(session['ht_profileid'], 'Bulk Acquisition ID: pending', start_time = start_time)
	if schedule:
		bulk_acquisition_task.set_schedule(**schedule)
	
	if download:
		bulk_download_eid = hxtool_global.hxtool_db.bulkDownloadCreate(session['ht_profileid'], hostset_id = hostset_id, task_profile = task_profile)
		bulk_acquisition_monitor_task = hxtool_scheduler_task(
											session['ht_profileid'], 
											'Bulk Acquisition Monitor Task', 
											parent_id = bulk_acquisition_task.task_id,
											start_time = bulk_acquisition_task.start_time
										)
	
		bulk_acquisition_monitor_task.add_step(
			bulk_download_monitor_task_module,
			kwargs = {
						'bulk_download_eid' : bulk_download_eid,
						'task_profile' : task_profile
			}
		)
		
		hxtool_global.hxtool_scheduler.add(bulk_acquisition_monitor_task)
		
		
	bulk_acquisition_task.add_step(
		bulk_acquisition_task_module, 
		kwargs = {
					'script' : script_xml,
					'hostset_id' : hostset_id,
					'comment' : comment,
					'skip_base64' : skip_base64,
					'download' : download,
					'bulk_download_eid' : bulk_download_eid
		}
	)
		
	hxtool_global.hxtool_scheduler.add(bulk_acquisition_task)
	
	return bulk_download_eid
	
def parse_schedule(request_params):
	start_time = None
	schedule = None
	
	schedule_type = request_params.get('schedule', None)
	if schedule_type:
		if schedule_type == "run_at":
			start_time = HXAPI.dt_from_str(request_params['run_at_value'])
		elif schedule_type == "run_interval":
			schedule = {}
			
			interval_value = int(request_params['interval_value'])
			interval_unit = request_params['interval_unit']
			
			if interval_unit == "second":
				schedule['seconds'] = interval_value
			elif interval_unit == "minute":
				schedule['minutes'] = interval_value
			elif interval_unit == "hour":
				schedule['hours'] = interval_value	
			elif interval_unit == "day":
				schedule['days'] = interval_value
			elif interval_unit == "week":
				schedule['weeks'] = interval_value
			elif interval_unit == "month":
				schedule['months'] = interval_value
				
			if request_params['interval_start'] == "interval_start_at":
				start_time = HXAPI.dt_from_str(request_params['interval_start_value'])

	return (start_time, schedule)
	
def js_path(json_string, path):
	try:
		for path_part in path.split("."):
			if path_part.startswith("#"):
				path_part = int(path_part[1:])
			json_string = json_string[path_part]
		return json_string
	except:
		return "Not found!"