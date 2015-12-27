#!/usr/bin/env python
"""
main.py -- Udacity conference server-side Python App Engine
    HTTP controller handlers for memcache & task queue access

$Id$

created by wesc on 2014 may 24

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'

import webapp2
from google.appengine.api import app_identity
from google.appengine.api import mail
from google.appengine.api import memcache
from google.appengine.ext import ndb

from models import Session

from conference import ConferenceApi

MEMCACHE_FEATURED_KEY = "FEATURED_SPEAKER"


class SetAnnouncementHandler(webapp2.RequestHandler):
    def get(self):
        """Set Announcement in Memcache."""
        ConferenceApi._cacheAnnouncement()
        self.response.set_status(204)


class SendConfirmationEmailHandler(webapp2.RequestHandler):
    def post(self):
        """Send email confirming Conference creation."""
        mail.send_mail('noreply@%s.appspotmail.com' % (
            app_identity.get_application_id()),  # from
                       self.request.get('email'),  # to
                       'You created a new Conference!',  # subj
                       'Hi, you have created a following '  # body
                       'conference:\r\n\r\n%s' %
                       self.request.get('conferenceInfo'))


class HandleFeaturedSpeaker(webapp2.RequestHandler):
    def post(self):
        speaker = self.request.get('speaker')
        speakerKey = ndb.Key(urlsafe=speaker)

        print("\n\n\n{}".format(self.request.get('conf')))
        conf = self.request.get('conf')
        confKey = ndb.Key(urlsafe=conf)

        numSessions = Session.query(
            ndb.AND(Session.speakerKey == speakerKey, Session.conferenceId ==
                    confKey)).count()
        if numSessions >= 2:
            memcache.set(MEMCACHE_FEATURED_KEY, speakerKey.get().name)


app = webapp2.WSGIApplication(
    [
        ('/crons/set_announcement', SetAnnouncementHandler),
        ('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
        ('/tasks/handle_featured_speaker', HandleFeaturedSpeaker),
    ],
    debug=True)
