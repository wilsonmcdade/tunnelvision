# Tunnelvision - An interactive catalog of RIT's Murals

## Running Locally
(Reach out to a maintainer of this repo for credentials for the dev database)


* Fork the repo and run the following commands in that directory:
* `pip install pipenv --user` (if you dont already have it installed)
* `pipenv install`
* `pipenv run python3 app.py`

## Database Schema
This project uses SQLAlchemy to access a PostgresQL database. The following is the (generated afterwards) DB schema:

```
create table artistmuralrelation (
  artist_id integer not null,
  mural_id integer not null,
  primary key (artist_id, mural_id),
  foreign key (artist_id) references artists (id)
  match simple on update no action on delete no action,
  foreign key (mural_id) references murals (id)
  match simple on update no action on delete no action
);

create table artists (
  id integer primary key not null default nextval('artists_id_seq'::regclass),
  name character varying(50),
  notes text
);

create table feedback (
  feedback_id integer primary key not null default nextval('feedback_feedback_id_seq'::regclass),
  notes text,
  time timestamp without time zone,
  mural_id integer,
  foreign key (mural_id) references murals (id)
  match simple on update no action on delete no action
);

create table imagemuralrelation (
  image_id integer not null,
  mural_id integer not null,
  primary key (image_id, mural_id)
);

create table images (
  id integer primary key not null default nextval('images_id_seq'::regclass),
  caption text,
  alttext text,
  ordering integer,
  imghash text,
  fullsizehash text
);

create table mural_tags (
  tag_id integer,
  mural_id integer,
  id integer primary key not null default nextval('mural_tags_id_seq'::regclass),
  foreign key (mural_id) references murals (id)
  match simple on update no action on delete no action,
  foreign key (tag_id) references tags (id)
  match simple on update no action on delete no action
);

create table murals (
  id integer primary key not null default nextval('murals_id_seq'::regclass),
  title character varying(50) default 'Unnamed',
  artistknown boolean default false,
  notes text,
  year integer,
  location character varying(100),
  nextmuralid integer,
  text_search_index tsvector default to_tsvector('english'::regconfig, (((((((COALESCE(title, ''))::text || ' '::text) || COALESCE(notes, ''::text)) || ' '::text) || COALESCE((year)::text, ''::text)) || ' '::text) || (COALESCE(location, ''))::text)),
  active boolean default true,
  spotify text,
  foreign key (nextmuralid) references murals (id)
  match simple on update no action on delete no action
);
create index muralsearch_idx on murals using gin (text_search_index);

create table tags (
  id integer primary key not null default nextval('tags_id_seq'::regclass),
  name character varying(255) not null,
  description text not null
);
```

## Docker:

- `podman compose up`
- go to http://localhost:9001 and add a bucket for TV
-
