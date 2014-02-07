#!/usr/bin/env python
#
# FailureLink post-processing script for NZBGet
#
# Copyright (C) 2013-2014 Andrey Prygunkov <hugbug@users.sourceforge.net>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#


##############################################################################
### NZBGET POST-PROCESSING SCRIPT                                          ###

# Inform indexer site about failed download and request a replacement nzb.
#
# If download fails, the script sends info about the failure to indexer site,
# so a replacement NZB (same movie or TV episode) can be queued up if
# available. The indexer site must support DNZB-Header "X-DNZB-FailureLink".
#
# Info about pp-script:
# Author: Andrey Prygunkov (nzbget@gmail.com).
# Web-site: http://nzbget.sourceforge.net/forum/viewforum.php?f=8.
# License: GPLv2 (http://www.gnu.org/licenses/gpl.html).
# PP-Script Version: 0.9.1.
#
# NOTE: The integration works only for downloads queued via URL (including
# RSS). NZB-files queued from local disk don't have enough information
# to contact the indexer site.
#
# NOTE: This script requires Python 2.x to be installed on your system.

##############################################################################
### OPTIONS																   ###

# Download another release (yes, no).
#
# If the NZB download of a Movie or TV Show fails, request an alternate
# NZB-file of the same release and add it to queue. If disabled the indexer
# site is still informed about the failure but no other nzb-file is queued.
#DownloadAnotherRelease=no

# Print more logging messages (yes, no).
#
# For debugging or if you need to report a bug.
#Verbose=no

### NZBGET POST-PROCESSING SCRIPT                                          ###
##############################################################################


import os
import sys
import urllib2
from subprocess import call
from xmlrpclib import ServerProxy
from base64 import standard_b64encode
import cgi

# Exit codes used by NZBGet
POSTPROCESS_SUCCESS=93
POSTPROCESS_NONE=95
POSTPROCESS_ERROR=94

# Check if the script is called from nzbget 12.0 or later
if not 'NZBOP_FEEDHISTORY' in os.environ:
	print('*** NZBGet post-processing script ***')
	print('This script is supposed to be called from nzbget (12.0 or later).')
	sys.exit(POSTPROCESS_ERROR)

# Init script config options
verbose = False
download_another_release=os.environ.get('NZBPO_DOWNLOADANOTHERRELEASE', 'yes') == 'yes'
verbose=os.environ.get('NZBPO_VERBOSE', 'no') == 'yes'

nzbget = None


def downloadNzb(failure_link):
	# Contact indexer site
	if download_another_release:
		print('[INFO] Requesting another release from indexer site')
	else:
		print('[INFO] Sending failure status to indexer site')
	sys.stdout.flush()
	
	nzbcontent = None
	headers = None
	
	try:
		headers = {'User-Agent' : 'NZBGet / FailureLink.py / Version 1.0'}
		req = urllib2.Request(failure_link, None, headers)
		response = urllib2.urlopen(req)
		if download_another_release:
			nzbcontent = response.read()
			headers = response.info()
	except Exception as err:
		print('[ERROR] %s' % err)
		sys.exit(POSTPROCESS_ERROR)

	return nzbcontent, headers


def connectToNzbGet():
	global nzbget
	
	# First we need to know connection info: host, port and password of NZBGet server.
	# NZBGet passes all configuration options to post-processing script as
	# environment variables.
	host = os.environ['NZBOP_CONTROLIP'];
	port = os.environ['NZBOP_CONTROLPORT'];
	username = os.environ['NZBOP_CONTROLUSERNAME'];
	password = os.environ['NZBOP_CONTROLPASSWORD'];
	
	if host == '0.0.0.0': host = '127.0.0.1'
	
	# Build an URL for XML-RPC requests
	# TODO: encode username and password in URL-format
	rpcUrl = 'http://%s:%s@%s:%s/xmlrpc' % (username, password, host, port);
	
	# Create remote server object
	nzbget = ServerProxy(rpcUrl)


def queueNzb(filename, category, nzbcontent64):
	# Adding nzb-file to queue
	# Signature:
	# append(string NZBFilename, string Category, int Priority, bool AddToTop, string Content,
	#     bool AddPaused, string DupeKey, int DupeScore, string DupeMode)
	nzbget.append(filename, category, 0, True, nzbcontent64, True, '', 0, 'ALL')

	# We need to find the id of the added nzb-file
	groups = nzbget.listgroups()
	groupid = 0;
	for group in groups:
		if verbose:
			print(group)
		if group['NZBFilename'] == filename:
			groupid = group['LastID']
			break;

	if verbose:
		print('GroupID: %i' % groupid)

	return groupid


def setupDnzbHeaders(groupid, headers):
	for header in headers.headers:
		if verbose:
			print(header.strip())
		if header[0:7] == 'X-DNZB-':
			name = header.split(':')[0].strip()
			value = headers.get(name)
			if verbose:
				print('%s=%s' % (name, value))
				
			# Setting "X-DNZB-" as post-processing parameter
			param = '*DNZB:%s=%s' % (name[7:], value)
			nzbget.editqueue('GroupSetParameter', 0, param, [groupid])


def unpauseGroup(groupid):
	nzbget.editqueue('GroupResume', 0, '', [groupid])


def main():
	# Check par and unpack status for errors.
	#  NZBPP_PARSTATUS    - result of par-check:
	#                       0 = not checked: par-check is disabled or nzb-file does
	#                           not contain any par-files;
	#                       1 = checked and failed to repair;
	#                       2 = checked and successfully repaired;
	#                       3 = checked and can be repaired but repair is disabled.
	#                       4 = par-check needed but skipped (option ParCheck=manual);
	#  NZBPP_UNPACKSTATUS - result of unpack:
	#                       0 = unpack is disabled or was skipped due to nzb-file
	#                           properties or due to errors during par-check;
	#                       1 = unpack failed;
	#                       2 = unpack successful.
	
	failure = os.environ['NZBPP_PARSTATUS'] == '1' or os.environ['NZBPP_UNPACKSTATUS'] == '1'
	
	failure_link = os.environ.get('NZBPR__DNZB_FAILURE')
	
	if not failure or failure_link == None or failure_link == '':
		sys.exit(POSTPROCESS_NONE)
	
	nzbcontent,headers = downloadNzb(failure_link)

	if not download_another_release:
		sys.exit(POSTPROCESS_SUCCESS)

	if verbose:
		print(headers)
	
	if nzbcontent == '' or nzbcontent[0:5] != '<?xml':
		print('[INFO] No other releases found')
		if verbose:
			print(nzbcontent)
		sys.exit(POSTPROCESS_SUCCESS)
	
	print('[INFO] Another release found, adding to queue')
	sys.stdout.flush()
	
	# Parsing filename from headers

	params = cgi.parse_header(headers.get('Content-Disposition', ''))
	if verbose:
		print(params)

	filename = params[1].get('filename', '')
	if verbose:
		print('filename: %s' % filename)
	
	# Parsing category from headers

	category = headers.get('X-DNZB-Category', '');
	if verbose:
		print('category: %s' % category)

	# Encode nzb-file content into base64
	nzbcontent64=standard_b64encode(nzbcontent)
	nzbcontent = None

	connectToNzbGet()
	groupid = queueNzb(filename, category, nzbcontent64)
	if groupid == 0:
		print('[WARNING] Could not find added nzb-file in the list of downloads')
		sys.stdout.flush()
		sys.exit(POSTPROCESS_ERROR)

	setupDnzbHeaders(groupid, headers)
	unpauseGroup(groupid)


main()

# All OK, returning exit status 'POSTPROCESS_SUCCESS' (int <93>) to let NZBGet know
# that our script has successfully completed.
sys.exit(POSTPROCESS_SUCCESS)
