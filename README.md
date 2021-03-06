App Engine application for the Udacity training course.

Design choices
--------------

### `Session` implementation

`Session`s have been implemented in a manner similar to `Conference`s.
Each `Session` is an ancestor of a single `Conference`, which can be
used in querying.

The `createSession()` method also puts a query into the taskqueue to
determine if the same speaker has ben registered for a second or
additional `Session`. If so, the taskqueue will set the `memcache` key
for `FEATURED_SPEAKER`.

The private `_copySessionToForm()` method handles the possibility that a
key could either be urlsafe (as when it is passed in as an argument for
an inquiry).

Several data fields in `Session` are `StringProperty`s: `name`
(required), `highlights` (a collection of strings), and
`typeOfSession`—all are strings. The `date` is handled as a DateProperty
and the `time` as a `TimeProperty`, straightforwardly enough. The third
party `dateutil` makes this feature robust against a variety of entries.
The `speakerKey` field is a `KeyProperty`, which provides some
protection against data-entry errors or malicious input. The `duration`
field is expressed in minutes as an `IntegerProperty`.

`Session`s are stored as keys to a wishlist held in user profiles.

### `Speaker` implementation and rationale

`Speaker`s are implemented as a model that contains only a name. An
alternative implementation would have been to permit speakers to be
created through the creation of a `Session`. But it should not
necessarily require any permission to create a `Speaker` because a
`Speaker` need not be associated with any particular `Conference` or
`Session`.

Methods involving `Speaker`s require key-based lookups. E.g.,
`getSessionBySpeaker()`

The `getFeaturedSpeaker()` method returns either a string corresponding
to the featured speaker’s name or an empty string if there is not a
featured speaker.

### Data modeling

`Session`s are modeled similarly to `Conference`s. `Session`s are
children of `Conference`s. `Speakers` can be in a one-to-many
relationship with `Session`s, which is the basis of determining a
featured speaker.

I have opted throughout for strong consistency rather than eventual
consistency. I recongize that this results in lower performance, but
until performance becomes an issue for a website for creating
conferences (which does not seem plausibly to require high performance),
I generally opted for accuracy over speed.

### Additional queries

The `query_noSeminarsOrLateNights()` works around the limitation on
inequality queries (caused by the requirement that two different
properties—time and type of session—have inequality filters) by
composing two separate queries as a set union. This method was suggested
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

1.  Run the app with the devserver using `dev_appserver.py DIR`, and
    ensure it’s running by visiting your local server’s address (by
    default [localhost:8080](https://localhost:8080/).)
2.  (Optional) Generate your client library(ies) with [the endpoints
    tool](https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool).
3.  To view the deployed instance of this app, visit
    <http://conference-1152.appspot.com>.
