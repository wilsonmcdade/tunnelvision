import os
import subprocess
from flask import Flask, render_template, request, redirect, abort, url_for
import psycopg2
import logging
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
import hashlib
import re
from functools import wraps
from random import shuffle
from PIL import Image as PilImage
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, ForeignKey, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from s3 import get_bucket, get_file_s3, upload_file, remove_file, get_file_list, get_file
from typing import Optional
import json_log_formatter

class Base(DeclarativeBase):
    pass

class Mural(Base):
    __tablename__ = "murals"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    artistknown: Mapped[bool]
    remarks: Mapped[str]
    notes: Mapped[str]
    private_notes: Mapped[str]
    year: Mapped[int]
    location: Mapped[str]
    nextmuralid: Mapped[Optional[int]] = mapped_column(ForeignKey("murals.id"))
    nextmural: Mapped[Optional["Mural"]] = relationship()
    active: Mapped[bool]
    spotify: Mapped[str]

class Artist(Base):
    __tablename__ = "artists"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    notes: Mapped[str]

class Image(Base):
    __tablename__ = "images"
    id: Mapped[int] = mapped_column(primary_key=True)
    caption: Mapped[str]
    alttext: Mapped[str]
    ordering: Mapped[int]
    imghash: Mapped[str]
    fullsizehash: Mapped[Optional[str]]

class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    description: Mapped[str]

class ArtistMuralRelation(Base):
    __tablename__ = "artistmuralrelation"
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id"), primary_key=True)
    artist: Mapped[Artist] = relationship()
    mural_id: Mapped[int] = mapped_column(ForeignKey("murals.id"), primary_key=True)
    mural: Mapped[Mural] = relationship()

class ImageMuralRelation(Base):
    __tablename__ = "imagemuralrelation"
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id"), primary_key=True)
    image: Mapped[Image] = relationship()
    mural_id: Mapped[int] = mapped_column(ForeignKey("murals.id"), primary_key=True)
    mural: Mapped[Mural] = relationship()

class MuralTag(Base):
    __tablename__ = "mural_tags"
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    tag: Mapped[Tag] = relationship()
    mural_id: Mapped[int] = mapped_column(ForeignKey("murals.id"), primary_key=True)
    mural: Mapped[Mural] = relationship()

class Feedback(Base):
    __tablename__ = "feedback"
    feedback_id: Mapped[int] = mapped_column(primary_key=True)
    notes: Mapped[str]
    contact: Mapped[str]
    time: Mapped[str]
    mural_id: Mapped[int] = mapped_column(ForeignKey("murals.id"))
    mural: Mapped[Mural] = relationship()

app = Flask(__name__)

formatter = json_log_formatter.JSONFormatter()
json_handler = logging.StreamHandler()
json_handler.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(json_handler)
logger.setLevel(logging.INFO)


logging.info("Starting up...")

if os.path.exists(os.path.join(os.getcwd(), "config.py")):
    app.config.from_pyfile(os.path.join(os.getcwd(), "config.py"))
else:
    app.config.from_pyfile(os.path.join(os.getcwd(), "config.env.py"))

git_cmd = ['git', 'rev-parse', '--short', 'HEAD']
app.config["GIT_REVISION"] = subprocess.check_output(git_cmd).decode('utf-8').rstrip()

logging.info("Connecting to S3 Bucket {0}".format(app.config["BUCKET_NAME"]))
s3_bucket = get_bucket(app.config["S3_URL"], app.config["S3_KEY"], app.config["S3_SECRET"], app.config["BUCKET_NAME"])

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://{0}:{1}@{2}:{3}/{4}'.format(
    app.config["DBUSER"],
    app.config["DBPWD"],
    app.config["DBHOST"],
    app.config["DBPORT"],
    app.config["DBNAME"],
)

logging.info("Connecting to DB {0}".format(app.config["DBNAME"]))

try:
    db = SQLAlchemy(app)
except KeyboardInterrupt:
    logging.error("Keyboard Interrupt during DB acquisition")

with app.app_context():
    db.create_all()

########################
#
#   Helpers
#
########################

"""
Create a JSON object for a mural
"""
def mural_json(mural: Mural):
    artists = []
    if mural.artistknown:
        artists = list(map(artist_json, db.session.execute(
            db.select(Artist)
                .join(ArtistMuralRelation, Artist.id == ArtistMuralRelation.artist_id)
                .where(ArtistMuralRelation.mural_id == mural.id)
        ).scalars()));

    prevmuralid = db.session.execute(
        db.select(Mural.id).where(Mural.nextmuralid == mural.id)
    ).scalar();

    image_data = db.session.execute(
        db.select(Image)
            .join(ImageMuralRelation, Image.id == ImageMuralRelation.image_id)
            .where(ImageMuralRelation.mural_id == mural.id)
    ).scalars()
    images = []
    thumbnail = None
    for image in image_data:
        if image.ordering == 0:
            thumbnail = get_file_s3(s3_bucket, image.imghash)
        else:
            images.append(image_json(image))

    return {
        "id": mural.id,
        "title": mural.title,
        "year": mural.year,
        "location": mural.location,
        "remarks": mural.remarks,
        "notes": mural.notes,
        "prevmuralid": prevmuralid,
        "nextmuralid": mural.nextmuralid,
        "private_notes": mural.private_notes,
        "active": "checked" if mural.active else "unchecked",
        "thumbnail": thumbnail,
        "artists": artists,
        "images": images,
        "spotify": mural.spotify
    }

"""
Create a JSON object for Feedback
"""
def feedback_json(feedback: Feedback):
    feedback = feedback[0]
    dt = datetime.now(timezone.utc)
    dt = dt.replace(tzinfo=None)
    fb_dt = feedback.time
    diff = dt-fb_dt

    return {
        "id": feedback.feedback_id,
        "mural_id": feedback.mural_id,
        "notes": feedback.notes,
        "contact": feedback.contact,
        "approxtime": "{0} days ago".format(diff.days), #approx_time,
        "exacttime": fb_dt
    }

"""
Create a JSON object for an artist
"""
def artist_json(artist: Artist):
    return {
        "id": artist.id,
        "name": artist.name
    }

"""
Create a JSON object for an image
"""
def image_json(image: Image):
    out = {
        "imgurl": get_file_s3(s3_bucket, image.imghash),
        "ordering": image.ordering,
        "caption": image.caption,
        "alttext": image.alttext,
        "id": image.id
    }
    if image.fullsizehash != None:
        out["fullsizeimage"] = get_file_s3(s3_bucket, image.fullsizehash)
    return out

"""
Crop a given image to a centered square
"""
def crop_center(pil_img, crop_width, crop_height):
    img_width, img_height = pil_img.size
    return pil_img.crop(((img_width - crop_width) // 2,
                         (img_height - crop_height) // 2,
                         (img_width + crop_width) // 2,
                         (img_height + crop_height) // 2))

"""
Search all murals given query
"""
def searchMurals(query):
    return list(map(mural_json, db.session.execute(
        db.select(Mural)
            .where(text(
                "murals.text_search_index @@ websearch_to_tsquery(:query)"
            ))
            .order_by(Mural.id)
            .limit(150),
        { "query": query }
    ).scalars()))

"""
Get murals in list, paginated
"""
def getMuralsPaginated(page_num):
    return list(map(mural_json, db.session.execute(
        db.select(Mural)
            .where(Mural.active == True)    
            .order_by(Mural.title.asc())
            .offset(page_num*app.config['ITEMSPERPAGE'])
            .limit(app.config['ITEMSPERPAGE'])
    ).scalars()))

"""
Get all murals
"""
def getAllMurals():
    return list(map(mural_json, db.paginate(
        db.select(Mural)
            .order_by(Mural.title.asc()),
        per_page=200,
    ).items))

"""
Get Feedback for a Mural
"""
def getMuralFeedback(mural_id):
    return list(map(feedback_json, db.session.execute(
        db.select(Feedback)
            .where(Feedback.mural_id == mural_id)
    )))

"""
Get all murals from year
"""
def getAllMuralsFromYear(year):
    return list(map(mural_json, db.paginate(
        db.select(Mural)
            .where(Mural.year == year)
            .order_by(Mural.title.asc()),
        per_page=150,
    ).items))

"""
Get all murals from artist given artist ID
"""
def getAllMuralsFromArtist(id):
    return list(map(mural_json, db.paginate(
        db.select(Mural)
            .join(ArtistMuralRelation, Mural.id == ArtistMuralRelation.mural_id)
            .where(ArtistMuralRelation.artist_id == id)
            .order_by(Mural.id.asc()),
        per_page=150,
    ).items))

"""
Get artist details
"""
def getArtistDetails(id):
    return artist_json(db.session.execute(
        db.select(Artist).where(Artist.id == id)
    ).scalar_one())

"""
Get mural details
"""
def getMural(id):
    mural = db.session.execute(
        db.select(Mural).where(Mural.id == id)
    ).scalar()

    if mural == None:
        logging.warning("DB Response was None")
        logging.warning("ID was '{0}'".format(id))
        return None

    muralInfo = mural_json(mural)
    logging.debug(muralInfo)
    return muralInfo

def checkYearExists(year):
    if not year.isdigit():
        return False

    integer_pattern = r'^[+-]?\d+$'

    # Use re.match to check if the variable matches the integer pattern
    if not re.match(integer_pattern, year):
        return False

    return True

def checkArtistExists(id):
    if not id.isdigit():
        return False

    integer_pattern = r'^[+-]?\d+$'

    # Use re.match to check if the variable matches the integer pattern
    if not re.match(integer_pattern, str(id)):
        return False

    return True

def checkMuralExists(id):
    # Check id is not bad
    if not id.isdigit():
        return False

    integer_pattern = r'^[+-]?\d+$'

    # Use re.match to check if the variable matches the integer pattern
    if not re.match(integer_pattern, str(id)):
        return False

    return True

"""
Get all murals with given tag
"""
def getMuralsTagged(tag):
    return list(map(mural_json, db.session.execute(
        db.select(Mural)
            .select_from(MuralTag)
            .join(Tag, MuralTag.tag_id == Tag.id)
            .join(Mural, Mural.id == MuralTag.mural_id)
            .where(Tag.name == tag)
    ).scalars()))

"""
Get all tags / Get all tags on certain mural
(logic based on whether mural_id is passed in)
"""
def getTags(mural_id=None):
    if (mural_id == None):
        return db.session.execute(
            db.select(Tag.name)
        ).scalars()
    else:
        return list(db.session.execute(
            db.select(Tag.name)
                .join(MuralTag, MuralTag.tag_id == Tag.id)
                .where(MuralTag.mural_id == mural_id)
        ).scalars())

"""
Get all artist IDs
"""
def getAllArtists():
    return list(map(artist_json, db.session.execute(
        db.select(Artist)
    ).scalars()))

"""
Get a random assortment of images from DB, excluding thumbnails
"""
def getRandomImages(count):
    images = list(map(image_json, 
        db.session.execute(
        db.select(Image)
            .where(Image.ordering != 0)
            .order_by(func.random())
            .limit(count))
            .scalars()))
    shuffle(images)
    return images

########################
#
#   Pages
#
########################

@app.route("/")
def home():
    return render_template("home.html", pageTitle="RIT's Overlooked Art Museum", muralHighlights=getRandomImages(8))

@app.route('/about')
def about():
    return render_template("about.html", muralHighlights=getRandomImages(0))

@app.route("/catalog?q=<query>")
@app.route("/catalog")
def catalog():
    query = request.args.get("q")
    if query == None:
        return render_template("catalog.html", q=query, murals=getMuralsPaginated(0))
    else:
        return render_template("filtered.html", pageTitle="Query - {0}".format(query), subHeading="Search Query", q=query, murals=searchMurals(query))

@app.route("/tags?t=<tag>")
@app.route("/tags")
def tags():
    tag = request.args.get("t")
    if tag == None:
        return render_template("404.html"), 404
    else:
        return render_template("filtered.html", pageTitle="Tag - {0}".format(tag), subHeading="Tagged", murals=getMuralsTagged(tag))

"""
Get next page of murals
"""
@app.route("/page?p=<page>")
@app.route("/page")
def paginated():
    page = int(request.args.get("p"))
    if page == None:
        #print("No page")
        return render_template("404.html"), 404
    else:
        return render_template("paginated.html", page=(page+1), murals=getMuralsPaginated(page))

"""
Page for specific mural details
"""
@app.route("/murals/<id>")
def mural(id):
    if (checkMuralExists(id)):
        return render_template("mural.html", muralDetails=getMural(id), tags=getTags(id), spotify=getMural(id)['spotify'])
    else:
        return render_template("404.html"), 404

"""
Page for specific artist
"""
@app.route("/artist/<id>")
def artist(id):
    if (checkArtistExists(id)):
        return render_template("filtered.html", pageTitle="Artist Search", subHeading=getArtistDetails(id), murals=getAllMuralsFromArtist(id))
    else:
        return render_template("404.html"), 404

"""
Page for specific year
"""
@app.route("/year/<year>")
def year(year):
    if (checkYearExists(year)):
        if (year == "0"):
            readableYear = "Unknown Date"
        else:
            readableYear = year
        return render_template("filtered.html", pageTitle="Murals from {0}".format(readableYear), subHeading=None, murals=getAllMuralsFromYear(year))
    else:
        return render_template("404.html"), 404

"""
Generic error handler
"""
@app.errorhandler(HTTPException)
def not_found(e):
    return render_template("404.html"), 404

########################
#
#   Management
#
########################

########################
# Helpers
########################

def debug_only(f):
    @wraps(f)
    def wrapped(**kwargs):
        if app.config["DEBUG"]:
            return f(**kwargs)
        return abort(404)
    return wrapped

def make_thumbnail(mural_id, file):

    with PilImage.open(file) as im:
        if (im.width == 256 or im.height == 256):
            # Already a thumbnail
            #print("Already a thumbnail...")
            return False
        im = crop_center(im, min(im.size), min(im.size))
        im.thumbnail((256,256))

        im = im.convert("RGB")
        im.save(file + ".thumbnail", "JPEG")

    with open(file + ".thumbnail", "rb") as tb:

        file_hash = hashlib.md5(tb.read()).hexdigest()
        tb.seek(0)

        # Upload thumnail version
        upload_file(s3_bucket, file_hash, tb, (file + ".thumbnail"))

        img = Image(
            imghash=file_hash,
            ordering=0
        )
        db.session.add(img)
        db.session.flush()

        img_id = img.id
        db.session.add(ImageMuralRelation(image_id=img_id, mural_id=mural_id))
        db.session.commit()

"""
Delete artist and all relations from DB
"""
def deleteArtistGivenID(id):
    db.session.execute(
        db.delete(ArtistMuralRelation)
            .where(ArtistMuralRelation.artist_id == id)
    )
    db.session.execute(
        db.delete(Artist)
            .where(Artist.id == id)
    )
    db.session.commit()

"""
Delete mural entry, all relations, and all images from DB and S3
"""
def deleteMuralEntry(id):
    # Get all images relating to this mural from the DB
    images = db.paginate(
        db.select(Image)
            .join(ImageMuralRelation, Image.id == ImageMuralRelation.image_id)
            .where(ImageMuralRelation.mural_id == id),
        per_page=150,
    ).items
    db.session.execute(
        db.delete(ImageMuralRelation)
            .where(ImageMuralRelation.mural_id == id)
    )
    db.session.execute(
        db.delete(ArtistMuralRelation)
            .where(ArtistMuralRelation.mural_id == id)
    )
    db.session.execute(
        db.delete(MuralTag)
            .where(MuralTag.mural_id == id)
    )
    db.session.execute(
        db.delete(Feedback)
            .where(Feedback.mural_id == id)
    )
    db.session.query(Mural).filter_by(nextmuralid = id).update({'nextmuralid' : None})
    db.session.execute(
        db.delete(Mural)
            .where(Mural.id == id)
    )
    for image in images:
        remove_file(s3_bucket, image.imghash)
        db.session.execute(
            db.delete(Image)
                .where(Image.id == image.id)
        )

    db.session.commit()

"""
Upload fullsize and resized image, add relation to mural given ID
"""
def uploadImageResize(file, mural_id, count):
    fullsizehash = hashlib.md5(file.read()).hexdigest()
    file.seek(0)

    # Upload full size img to S3
    upload_file(s3_bucket, fullsizehash, file)

    with PilImage.open(file) as im:
        width = (im.width * app.config["MAX_IMG_HEIGHT"]) // im.height

        (width, height) = (width, app.config["MAX_IMG_HEIGHT"])
        #print(width, height)
        im = im.resize((width,height))

        im = im.convert("RGB")
        im.save(fullsizehash + ".resized", "JPEG")

    with open((fullsizehash + ".resized"), "rb") as rs:

        file_hash = hashlib.md5(rs.read()).hexdigest()
        rs.seek(0)

        upload_file(s3_bucket, file_hash, rs, filename=fullsizehash+".resized")

        #print(get_file_s3(s3_bucket, file_hash))

        img = Image(
            fullsizehash=fullsizehash,
            ordering=count,
            imghash=file_hash
        )
        db.session.add(img)
        db.session.flush()
        img_id = img.id
        db.session.add(ImageMuralRelation(image_id=img_id, mural_id=mural_id))
    db.session.commit()

########################
#   Pages
########################

"""
Route to edit mural page
"""
@app.route('/edit/<id>')
@debug_only
def edit(id):
    return render_template("edit.html", muralDetails=getMural(id), muralFeedback=getMuralFeedback(id))

"""
Route to the admin panel
"""
@app.route("/admin")
@debug_only
def admin():
    return render_template("admin.html", murals=getAllMurals(), artists=getAllArtists())


########################
#   Form submissions
########################

"""
Suggestion/feedback form
"""
@app.route("/suggestion", methods=["POST"])
def submit_suggestion():

    dt = datetime.now(timezone.utc)

    db.session.add(Feedback(
        notes=request.form["notes"],
        contact=request.form["contact"],
        time=str(dt),
        mural_id=request.form["muralid"]
    ))
    db.session.commit()

    return redirect("/catalog")

"""
Route to delete artist
"""
@app.route('/deleteArtist/<id>', methods=["POST"])
@debug_only
def deleteArtist(id):
    if checkArtistExists(id):
        deleteArtistGivenID(id)
        return redirect("/admin")
    else:
        return render_template("404.html"), 404

"""
Route to delete mural entry
"""
@app.route('/delete/<id>', methods=["POST"])
@debug_only
def delete(id):
    if checkMuralExists(id):
        deleteMuralEntry(id)
        return redirect("/admin")
    else:
        return render_template("404.html"), 404

"""
Route to edit mural details
Sets all trivial fields based on http form
"""
@app.route('/editmural/<id>', methods=['POST'])
@debug_only
def editMural(id):
    m = db.session.execute(
        db.select(Mural).where(Mural.id == id)
    ).scalar_one()

    m.active = True if 'active' in request.form else False
    m.notes = request.form['notes']
    m.remarks = request.form['remarks']
    m.year = int(request.form['year'])
    m.location = request.form['location']
    m.private_notes = request.form['private_notes']
    db.session.commit()
    return ('', 204)


"""
Route to edit mural title
Sets mural title based on http form
"""
@app.route('/edittitle/<id>', methods=['POST'])
@debug_only
def editTitle(id):
    m = db.session.execute(
        db.select(Mural).where(Mural.id == id)
    ).scalar_one()
    m.title = request.form['title']
    db.session.commit()
    return ('', 204)

"""
Route to edit image details
Set caption and alttext based on http form
"""
@app.route('/editimage/<id>', methods=["POST"])
@debug_only
def editImage(id):
    image = db.session.execute(
        db.select(Image).where(Image.id == id)
    ).scalar_one()
    image.caption = request.form["caption"]
    image.alttext = request.form["alttext"]
    db.session.commit()
    return ('', 204)

"""
Replaces mural thumbnail with selected image
Route:
    /makethumbnail?muralid=m_id&imageid=i_id
"""
@app.route('/makethumbnail', methods=["POST"])
@debug_only
def makeThumbnail():
    mural_id  = request.args.get('muralid', None)
    image_id  = request.args.get('imageid', None)

    # Delete references to current thumbnail
    curr_thumbnail = db.session.execute(
        db.select(Image)
            .join(ImageMuralRelation, ImageMuralRelation.image_id == Image.id)
            .where(ImageMuralRelation.mural_id == mural_id)
            .filter(Image.ordering == 0)
    ).scalar_one()

    db.session.execute(
        db.delete(ImageMuralRelation)
            .where(ImageMuralRelation.image_id == curr_thumbnail.id)
    )
    db.session.execute(
        db.delete(Image)
            .where(Image.id == curr_thumbnail.id)
    )

    # Download base photo, turn it into thumbnail
    image = db.session.execute(
        db.select(Image)
            .where(Image.id == image_id)
    ).scalar_one()
    newfilename = '/tmp/{0}.thumb'.format(image.id)

    get_file(app.config['BUCKET_NAME'], image.imghash, newfilename, app.config['S3_KEY'], app.config['S3_SECRET'])
    make_thumbnail(mural_id, newfilename)
    
    return redirect("/edit/{0}".format(mural_id))

"""
Route to delete image
"""
@app.route('/deleteimage/<id>', methods=["POST"])
@debug_only
def deleteImage(id):
    images = db.session.execute(
        db.select(Image).where(Image.id == id)
    ).scalars()

    for image in images:
        remove_file(s3_bucket, image.imghash)
    db.session.execute(
        db.delete(ImageMuralRelation)
            .where(ImageMuralRelation.image_id == id)
    )
    db.session.execute(
        db.delete(Image)
            .where(Image.id == id)
    )
    db.session.commit()

    return redirect("/edit/{0}".format(id))

"""
Route to upload new image
"""
@app.route("/uploadimage/<id>", methods=["POST"])
@debug_only
def uploadNewImage(id):
    count = db.session.execute(
        db.select(func.count())
            .where(ImageMuralRelation.mural_id == id)
    ).scalar()

    for f in request.files.items(multi=True):
        uploadImageResize(f[1], id, count)
        count += 1

    return redirect("/edit/{0}".format(id))

"""
Route to add new mural entry
"""
@app.route("/upload", methods=["POST"])
@debug_only
def upload():
    artistKnown = True if request.form['artistknown'] else False
    if not (request.form["year"].isdigit()):
        return render_template("404.html"), 404

    mural = Mural(
        title=request.form["title"],
        artistknown=artistKnown,
        notes=request.form["notes"],
        year=request.form["year"],
        location=request.form["location"],
        active=False
    )
    db.session.add(mural)
    db.session.flush()
    mural_id = mural.id

    # Count is the order in which the images are shown
    #   0 is the thumbnail (only shown on mural card)
    #   All other values denote the order shown in the image carousel
    count = 0
    for f in request.files.items(multi=True):
        filename = secure_filename(f[1].filename)
        #print(f[1].filename)

        fullsizehash = hashlib.md5(f[1].read()).hexdigest()
        f[1].seek(0)

        # Check if image is already used in DB
        count = db.session.execute(
            db.select(func.count())
                .where(Image.imghash == fullsizehash)
        ).scalar()
        if (count > 0):
            #print(fullsizehash)
            return render_template("404.html"), 404

        # Begin creating thumbnail version
        if count == 0:
            with open(fullsizehash, 'wb') as file:
                f[1].seek(0)
                f[1].save(file)

            with PilImage.open(fullsizehash) as im:
                if (im.width == 256 or im.height == 256):
                    # Already a thumbnail
                    #print("Already a thumbnail...")
                    continue
                im = crop_center(im, min(im.size), min(im.size))
                im.thumbnail((256,256))

                im = im.convert("RGB")
                im.save(fullsizehash + ".thumbnail", "JPEG")

            with open(fullsizehash + ".thumbnail", "rb") as tb:

                file_hash = hashlib.md5(tb.read()).hexdigest()
                tb.seek(0)

                # Upload thumnail version
                upload_file(s3_bucket, file_hash, tb, (fullsizehash + ".thumbnail"))
                img = Image(
                    imghash=file_hash,
                    ordering=0
                )
                db.session.add(img)
                db.session.flush()
                img_id = img.id
                db.session.add(ImageMuralRelation(image_id=img_id, mural_id=mural_id))

            db.session.commit()
            count += 1

        # Begin adding full size to database
        f[1].seek(0)

        uploadImageResize(f[1], mural_id, count)

        count += 1

    if (artistKnown):
        artists = request.form["artists"].split(',')
        for artist in artists:
            count = db.session.execute(
                db.select(func.count())
                    .where(Artist.name == artist)
            ).scalar()
            artist_id = None
            if(count > 0):
                artist_id = db.session.execute(
                    db.select(Artist.id)
                        .where(Artist.name == artist)
                ).scalar()
            else:
                artist_obj = Artist(name=artist)
                db.session.add(artist_obj)
                db.session.flush()
                artist_id = artist_obj.id

            rel = ArtistMuralRelation(artist_id=artist_id, mural_id=mural_id)
            db.session.add(rel)

    db.session.commit()

    return redirect("/edit/{0}".format(mural_id))

if __name__ == "__main__":
    if not app.config["DEBUG"]:
        app.run(host="0.0.0.0", port=8080)
    else:
        app.run()
