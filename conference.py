#!/usr/bin/env python
"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'

from datetime import datetime, date, time, timedelta

import endpoints
from dateutil.parser import parse
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Session
from models import SessionForm
from models import SessionForms
from models import Speaker
from models import SpeakerForm
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForms
from models import TeeShirtSize

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
MEMCACHE_FEATURED_KEY = "FEATURED_SPEAKER"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": ["Default", "Topic"],
}

OPERATORS = {
    'EQ': '=',
    'GT': '>',
    'GTEQ': '>=',
    'LT': '<',
    'LTEQ': '<=',
    'NE': '!='
}

FIELDS = {
    'CITY': 'city',
    'TOPIC': 'topics',
    'MONTH': 'month',
    'MAX_ATTENDEES': 'maxAttendees',
}

GET_OR_DELETE_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    inputString=messages.StringField(1), )

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    inputString=messages.StringField(1), )

SESS_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    inputString=messages.StringField(1), )

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(
    name='conference',
    version='v1',
    audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[
        WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID
    ],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

    # - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """Create or update Conference object, returning
        ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException(
                "Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound
        # Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on
        # start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10],
                                                  "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10],
                                                "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        print(Conference(**data).put().urlsafe())  # for debugging
        # Conference(**data).put().urlsafe()  # for production
        taskqueue.add(params={'email': user.email(),
                              'conferenceInfo': repr(request)},
                      url='/tasks/send_confirmation_email')
        return request

    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.inputString).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.inputString)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        print(conf.put().urlsafe())  # For debugging
        # conf.put()  # For production
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(ConferenceForm,
                      ConferenceForm,
                      path='conference',
                      http_method='POST',
                      name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    @endpoints.method(CONF_POST_REQUEST,
                      ConferenceForm,
                      path='conference/{inputString}',
                      http_method='PUT',
                      name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)

    @endpoints.method(GET_OR_DELETE_REQUEST,
                      ConferenceForm,
                      path='conference/{inputString}',
                      http_method='GET',
                      name='getConference')
    def getConference(self, request):
        """Return requested conference (by inputString)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.inputString).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.inputString)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(message_types.VoidMessage,
                      ConferenceForms,
                      path='getConferencesCreated',
                      http_method='POST',
                      name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, getattr(
            prof, 'displayName')) for conf in confs])

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(
                filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q

    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name)
                     for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException(
                    "Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous
                # filters disallow the filter if inequality was performed on a
                # different field before track the field on which the

                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException(
                        "Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)

    @endpoints.method(ConferenceQueryForms,
                      ConferenceForms,
                      path='queryConferences',
                      http_method='POST',
                      name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId))
                      for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[
            conf.organizerUserId]) for conf in conferences])

# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize,
                                                    getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if
        non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(key=p_key,
                              displayName=user.nickname(),
                              mainEmail=user.email(),
                              teeShirtSize=str(TeeShirtSize.NOT_SPECIFIED), )
            print(profile.put().urlsafe())  # for debugging
            # profile.put()  # for production

        return profile  # return Profile

    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        # if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        # else:
                        #    setattr(prof, field, val)
                        print(prof.put().urlsafe())  # for debugging
                        # prof.put()  # for productiong

                        # return ProfileForm
        return self._copyProfileToForm(prof)

    @endpoints.method(message_types.VoidMessage,
                      ProfileForm,
                      path='profile',
                      http_method='GET',
                      name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    @endpoints.method(ProfileMiniForm,
                      ProfileForm,
                      path='profile',
                      http_method='POST',
                      name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)

# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(Conference.seatsAvailable <= 5,
                                         Conference.seatsAvailable > 0)).fetch(
                                             projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (', '.join(conf.name
                                                         for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @endpoints.method(message_types.VoidMessage,
                      StringMessage,
                      path='conference/announcement/get',
                      http_method='GET',
                      name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(
            data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")

# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser()  # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.inputString
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException("There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    @endpoints.method(message_types.VoidMessage,
                      ConferenceForms,
                      path='conferences/attending',
                      http_method='GET',
                      name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser()  # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck)
                     for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId)
                      for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[
            conf.organizerUserId]) for conf in conferences])

    @endpoints.method(GET_OR_DELETE_REQUEST,
                      BooleanMessage,
                      path='conference/{inputString}',
                      http_method='POST',
                      name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(GET_OR_DELETE_REQUEST,
                      BooleanMessage,
                      path='conference/{inputString}',
                      http_method='DELETE',
                      name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)

    # ####################################################################### #
    # Session methods                                                         #
    # ####################################################################### #

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #
    # Session creation and retrieval                                          #
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #

    def _copySessionToForm(self, sess):
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(sess, field.name):
                if (field.name == "date" or field.name == "time") and getattr(
                        sess, field.name):
                    setattr(sf, field.name, str(getattr(sess, field.name)))
                elif field.name == 'speakerKey':
                    # Handle possibility that key is a key or urlsafe key
                    if type(getattr(sess, field.name)) == ndb.Key:
                        setattr(sf, field.name, getattr(sess,
                                                        field.name).urlsafe())
                    else:
                        setattr(sf, field.name, getattr(sess, field.name))
                else:
                    setattr(sf, field.name, getattr(sess, field.name))
        sf.check_initialized()
        return sf

    @endpoints.method(SESS_POST_REQUEST,
                      SessionForm,
                      path='sessions',
                      http_method='POST',
                      name='createSession')
    def createSession(self, request):
        """Create new Session."""

        # get the conference
        conf = ndb.Key(urlsafe=request.inputString).get()
        # check that conference exists
        if not conf:
            raise endpoints.notfoundexception(
                'no conference found with key: %s' % request.inputString)

        # user verification
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Verify name
        if not request.name:
            raise endpoints.BadRequestException(
                "Session 'name' field required")

        data = {}
        for field in request.all_fields():
            if field.name == "date" and getattr(request, field.name):
                data[field.name] = parse(getattr(request, field.name)).date()
            elif field.name == "time" and getattr(request, field.name):
                data[field.name] = parse(getattr(request, field.name)).time()
            elif field.name == "speakerKey":
                data[field.name] = ndb.Key(
                    urlsafe=getattr(request, field.name))
            elif field.name == "inputString":
                pass
            else:
                data[field.name] = getattr(request, field.name)

        p_key = ndb.Key(Conference, conf.key.id())
        s_id = Session.allocate_ids(size=1, parent=p_key)[0]
        s_key = ndb.Key(Session, s_id, parent=p_key)
        data['key'] = s_key
        data['conferenceId'] = conf.key
        sess = Session(**data).put()
        print(sess.urlsafe())  # for debugging

        # Put handling the featured speaker logic on the taskqueue
        if data['speakerKey']:
            taskqueue.add(params={'speaker': getattr(request, 'speakerKey'),
                                  'conf': conf.key.urlsafe()},
                        url='/tasks/handle_featured_speaker')

        return self._copySessionToForm(request)

    @endpoints.method(GET_OR_DELETE_REQUEST,
                      SessionForms,
                      path='sesssions/{inputString}',
                      http_method='GET',
                      name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Given a conference, return all sessions."""
        wsck = request.inputString
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)
        sessionObjects = Session.query(Session.conferenceId == conf.key).fetch(
        )
        print(str(sessionObjects))
        sessionForms = [self._copySessionToForm(sess)
                        for sess in sessionObjects]
        return SessionForms(items=sessionForms)

    @endpoints.method(GET_OR_DELETE_REQUEST,
                      SessionForms,
                      path='sessions/speaker/{inputString}',
                      http_method='GET',
                      name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Returns all Sessions matching the speaker."""
        urlSafeKey = request.inputString
        key = ndb.Key(urlsafe=urlSafeKey)
        sessionObjects = Speaker.query(ancestor=key).fetch()
        if sessionObjects:
            return SessionForms(items=[self._copySessionToForm(sess)
                                       for sess in sessionObjects])
        raise endpoints.NotFoundException(
            'No session found with speaker {}'.format(request.inputString))

    @endpoints.method(GET_OR_DELETE_REQUEST,
                      SessionForms,
                      path='sessions/{inputString}',
                      http_method='GET',
                      name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Returns all Sessions matching the session type."""
        sessionObjects = Session.query(Session.typeOfSession == getattr(
            request, 'inputString')).fetch()
        if sessionObjects:
            return SessionForms(items=[self._copySessionToForm(sess)
                                       for sess in sessionObjects])
        raise endpoints.NotFoundException(
            'No session found with session type {}'.format(
                request.inputString))

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #
    # Session wishlist methods                                                #
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - #

    def _getUserProf(self):
        """Abstracts out common portions of wishlist methods."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        prof = ndb.Key(Profile, user_id).get()
        return prof

    @endpoints.method(GET_OR_DELETE_REQUEST,
                      message_types.VoidMessage,
                      path='wishlist/{inputString}',
                      http_method='GET',
                      name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add session to user wishlist."""

        prof = self._getUserProf()
        sess = ndb.Key(urlsafe=request.inputString).get()
        if not sess:
            raise endpoints.NotFoundException(
                'No session found with key: {}'.format(request.inputString))

        # Add to wishlist (or make a new one if empty)
        currentWishlist = getattr(prof, 'userWishlist')

        if sess.key in currentWishlist:  # Handle attempt to add twice.
            raise endpoints.BadRequestException(
                'Session with key {} already in wishlist.'.format(
                    request.inputString))

        updatedWishlist = currentWishlist.append(
            sess.key) if currentWishlist else [sess.key]

        setattr(prof, 'userWishlist', updatedWishlist)
        print(prof.put().urlsafe())  # for debugging
        # prof.put()
        return message_types.VoidMessage()

    # Assignment interpreted per https://goo.gl/HlVAVK
    @endpoints.method(message_types.VoidMessage,
                      SessionForms,
                      path='wishlist',
                      http_method='GET',
                      name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Return all wishlisted sessions for signed-in user."""
        prof = self._getUserProf()
        wishlistKeys = getattr(prof, 'userWishlist')
        if not wishlistKeys:
            return SessionForms([])

        sessionForms = [self._copySessionToForm(key.get())
                        for key in wishlistKeys]
        return SessionForms(items=sessionForms)

    @endpoints.method(GET_OR_DELETE_REQUEST,
                      message_types.VoidMessage,
                      path='wishlist/{inputString}',
                      http_method='DELETE',
                      name='deleteSessionInWishlist')
    def deleteSessionInWishlist(self, request):
        """Delete a session from wishlist."""
        prof = self._getUserProf()
        sess = ndb.Key(urlsafe=request.inputString).get()
        if not sess:
            raise endpoints.NotFoundException(
                'No session found with key: {}'.format(request.inputString))
        currentWishlist = getattr(prof, 'userWishlist')
        try:
            updatedWishlist = currentWishlist.remove(sess.key)
            if not updatedWishlist:
                setattr(prof, 'userWishlist', [])
            else:
                setattr(prof, 'userWishlist', updatedWishlist)
            print(prof.put().urlsafe())  # for debugging
            # prof.put()  # for production
        except ValueError:
            raise endpoints.NotFoundException(
                'Session with key {} not in wishlist.'.format(
                    request.inputString))
        return message_types.VoidMessage()

    # ####################################################################### #
    # Speaker methods                                                         #
    # ####################################################################### #

    @endpoints.method(SpeakerForm,
                      SpeakerForm,
                      path='speaker',
                      http_method='POST',
                      name='createSpeaker')
    def createSpeaker(self, request):
        """Create a speaker."""
        if not request.name:
            raise endpoints.BadRequestException(
                "Speaker 'name' field required")

        speaker = Speaker(name=request.name)
        print(speaker.put().urlsafe())  # for debugging
        # speaker.put()  # for production
        return request

    @endpoints.method(GET_OR_DELETE_REQUEST,
                      SpeakerForm,
                      path='speaker/{inputString}',
                      http_method='GET',
                      name='getSpeaker')
    def getSpeaker(self, request):
        """Given a websafe key, returns the appropriate speaker."""
        speaker = ndb.Key(urlsafe=request.inputString).get()
        if not speaker:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.inputString)
        return SpeakerForm(name=getattr(speaker, 'name'))

    @endpoints.method(message_types.VoidMessage,
                      StringMessage,
                      path='featured',
                      http_method='GET',
                      name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Returns the name of the featured speaker if set else empty
        string."""
        featured = memcache.get(MEMCACHE_FEATURED_KEY) or ""
        return StringMessage(data=featured)

    # taskqueue.add(params={'email': user.email(),
    #                         'conferenceInfo': repr(request)},
    #                 url='/tasks/send_confirmation_email')

    # ####################################################################### #
    # Queries                                                                 #
    # ####################################################################### #

    @endpoints.method(message_types.VoidMessage,
                      SessionForms,
                      path='queries1',
                      http_method='GET',
                      name='query_noSeminarsOrLateNights')
    def query_noSeminarsOrLateNights(self, request):
        """How would you handle a query for all non-workshop sessions before 7
        pm?"""

        # As suggested here: http://goo.gl/HtsZT2
        q1 = Session.query(Session.typeOfSession != 'Workshop').fetch(
            keys_only=True)
        q2 = Session.query(Session.time < time(19)).fetch(keys_only=True)
        sessionObjects = ndb.get_multi(set(q1).intersection(q2))
        sessionForms = [self._copySessionToForm(sess)
                        for sess in sessionObjects]
        return SessionForms(items=sessionForms)

    @endpoints.method(message_types.VoidMessage,
                      SessionForms,
                      path='queries2',
                      http_method='GET',
                      name='query_afterLunchSessions')
    def query_afterLunchSessions(self, request):
        """Select only sessions starting after 1 p.m."""
        sessionObjects = Session.query(Session.time >= time(13)).fetch()
        sessionForms = [self._copySessionToForm(sess)
                        for sess in sessionObjects]
        return SessionForms(items=sessionForms)

    @endpoints.method(message_types.VoidMessage,
                      ConferenceForms,
                      path='queries3',
                      http_method='GET',
                      name='query_smallConferences')
    def query_smallConferences(self, request):
        """Select only conferences with fewer than 50 maxAttendees."""
        conferenceObjects = Conference.query(Conference.maxAttendees < 50)
        conferenceForms = []
        if conferenceObjects:
            for conf in conferenceObjects:
                displayName = None
                if hasattr(conf.key.parent().get(), 'displayName'):
                    displayName = getattr(conf.key.parent().get(),
                                          'displayName')
                form = self._copyConferenceToForm(conf, displayName)
                conferenceForms.append(form)
        return ConferenceForms(items=conferenceForms)

api = endpoints.api_server([ConferenceApi])  # register API
