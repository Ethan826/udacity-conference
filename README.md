App Engine application for the Udacity training course.

Design choices
--------------

### `Session` implementation

`Session`s have been implemented in a manner similar to `Conference`s.
Each `Session` holds its parent’s `conferenceId()` of type
`ndb.KeyProperty`.

The `createSession()` method also monitors for the same speaker being
registered for a second or additional `Session` and sets the `memcache`
key for `FEATURED_SPEAKER`.

The private \_copy`Session`ToForm() method handles the possibility that
a key could either be urlsafe (as when it is passed in as an argument
for an inquiry).

`Session`s are stored as keys to a wishlist held in user profiles.

### `Speaker` implementation and rationale

`Speaker`s are implemented as a model that contains only a name. An
alternative implementation would have been to permit speakers to be
created through the creation of a `Session`. But it should not
necessarily require any permission to create a `Speaker` because a
`Speaker` need not be associated with any particular `Conference` or
`Session`.

The `getFeaturedSpeaker()` method returns either a string corresponding
to the featured speaker’s name or an empty string if there is not a
featured speaker.

### Data modeling

`Session`s are modeled similarly to `Conference`s. `Session`s are
children of `Conference`s. `Speakers` can be in a one-to-many
relationship with `Session`s, which is the basis of determining a
featured speaker.

### Additional queries

The `query_noSeminarsOrLateNights()` works around the limitation on
inequality queries (caused by the requirement that two different
properties—time and type of session—have inequality filters) by
composing two separate queries as a set. This method was suggested
[here](http://goo.gl/HtsZT2).

The additional queries are straightforward. The
`query_afterLunchSessions()` method works by returning all `Session`s
after 1 p.m. The `query_smallConferences()` method returns all
`Conference`s with fewer than 50 seats available.

Products
--------

-   [App Engine](https://developers.google.com/appengine)

Language
--------

-   [Python](http://python.org)

APIs
----

-   [Google Cloud
    Endpoints](https://developers.google.com/appengine/docs/python/endpoints/)

Setup Instructions
------------------

1.  Update the value of `application` in `app.yaml` to the app ID you
    have registered in the App Engine admin console and would like to
    use to host your instance of this sample.
2.  Update the values at the top of `settings.py` to reflect the
    respective client IDs you have registered in the [Developer
    Console](https://console.developers.google.com/).
3.  Update the value of CLIENT\_ID in `static/js/app.js` to the Web
    client ID
4.  (Optional) Mark the configuration files as unchanged as follows:
    `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
5.  Run the app with the devserver using `dev_appserver.py DIR`, and
    ensure it’s running by visiting your local server’s address (by
    default [localhost:8080](https://localhost:8080/).)
6.  (Optional) Generate your client library(ies) with [the endpoints
    tool](https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool).
7.  Deploy your application.
