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
from PIL import Image
from datetime import datetime, timezone
from s3 import get_bucket, get_file_s3, upload_file, remove_file, get_file_list

app = Flask(__name__)
logging.info("Starting up...")

if os.path.exists(os.path.join(os.getcwd(), "config.py")):
    app.config.from_pyfile(os.path.join(os.getcwd(), "config.py"))
else:
    app.config.from_pyfile(os.path.join(os.getcwd(), "config.env.py"))

git_cmd = ['git', 'rev-parse', '--short', 'HEAD']
app.config["GIT_REVISION"] = subprocess.check_output(git_cmd).decode('utf-8').rstrip()

print("Connecting to S3 Bucket {0}".format(app.config["BUCKET_NAME"]))
s3_bucket = get_bucket(app.config["S3_URL"], app.config["S3_KEY"], app.config["S3_SECRET"], app.config["BUCKET_NAME"])

print("Connecting to DB {0}".format(app.config["DBNAME"]))
conn = psycopg2.connect(**{
        "database": app.config["DBNAME"],
        "user": app.config["DBUSER"],
        "password": app.config["DBPWD"],
        "host": app.config["DBHOST"],
        "port": app.config["DBPORT"]
    })

########################
#
#   Helpers
#
########################

"""
Handle DB response for mural details, put into JSON obj
"""
def handleMuralDBResp(dbResp):
    cursor = conn.cursor()

    # Should really be using an ORM...
    muralInfo = {
        "id":  0,
        "title": "",
        "year": 0,
        "location": "",
        "notes": "",
        "prevmuralid": None,
        "nextmuralid": None,
        "active": False,
        "primaryimage": "",
        "artists": [],
        "images": []
    }

    artists = []

    if dbResp[6] == True:
        cursor.execute("select artists.id AS id, artists.name AS name from artists left join artistMuralRelation on artists.id = artistMuralRelation.artist_id where mural_id = %s", (dbResp[0], ))
        artists = cursor.fetchall()

    cursor.execute("select id from murals where nextmuralid = %s", (dbResp[0], ))
    prevmuralid = cursor.fetchone()

    muralInfo["id"] = dbResp[0]
    muralInfo["title"] = dbResp[1]
    muralInfo["notes"] = dbResp[2]
    muralInfo["year"] = dbResp[3]
    muralInfo["location"] = dbResp[4]
    if ((prevmuralid != None) and (len(prevmuralid) > 0)):
        muralInfo["prevmuralid"] = prevmuralid[0]
    muralInfo["nextmuralid"] = dbResp[5]

    if (len(dbResp) > 7):
        muralInfo["active"] = dbResp[7]

    cursor.execute("select images.imghash as imghash, images.ordering as ordering, images.caption AS caption, images.alttext AS alttext, images.id as id, images.fullsizehash from images left join imageMuralRelation on images.id = imageMuralRelation.image_id where imageMuralRelation.mural_id = %s;", (dbResp[0], ))
    images = cursor.fetchall()

    if (images != None):
        for image in images:
            if image[1] == 0:
                muralInfo["primaryimage"] = get_file_s3(s3_bucket,image[0])
                continue

            if image[5] == None:
                img = {
                    "imgurl":get_file_s3(s3_bucket,image[0]),
                    "ordering":image[1],
                    "caption":image[2],
                    "alttext":image[3],
                    "id":image[4]}
            else:
                img = {
                    "imgurl":get_file_s3(s3_bucket,image[0]),
                    "ordering":image[1],
                    "caption":image[2],
                    "alttext":image[3],
                    "id":image[4],
                    "fullsizeimage":get_file_s3(s3_bucket,image[5])}
                
            muralInfo["images"].append(img)

    for artist in artists:
        muralInfo["artists"].append({"name":artist[1],"id":artist[0]})

    return muralInfo

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
    curs = conn.cursor()
    curs.execute("select id, title, notes, year, location, nextmuralid, artistKnown from murals where text_search_index @@ websearch_to_tsquery(%s) order by id;", (query, ))

    murals = curs.fetchmany(150)
    returnable = []

    for mural in murals:
        returnable.append(handleMuralDBResp(mural))

    return returnable

"""
Get murals in list, paginated
"""
def getMuralsPaginated(pageNum):
    curs = conn.cursor()

    curs.execute("select id, title, notes, year, location, nextmuralid, artistKnown from murals where active=true order by title asc offset %s limit %s", (app.config["ITEMSPERPAGE"] * pageNum, app.config["ITEMSPERPAGE"]))
    murals = curs.fetchmany(app.config['ITEMSPERPAGE'])
    returnable = []

    for mural in murals:
        returnable.append(handleMuralDBResp(mural))

    return returnable

"""
Get all murals
"""
def getAllMurals():
    cursor = conn.cursor()
    cursor.execute("select id, title, notes, year, location, nextmuralid, artistKnown from murals order by title asc")
    murals = cursor.fetchmany(200)
    returnable = []

    for mural in murals:
        returnable.append(handleMuralDBResp(mural))

    return returnable

"""
Get all murals from year
"""
def getAllMuralsFromYear(year):
    cursor = conn.cursor()
    cursor.execute("select id, title, notes, year, location, nextmuralid, artistKnown from murals where year = %s order by id asc", (year,))
    murals = cursor.fetchmany(150)
    returnable = []

    for mural in murals:
        returnable.append(handleMuralDBResp(mural))

    return returnable

"""
Get all murals from artist given artist ID
"""
def getAllMuralsFromArtist(id):
    cursor = conn.cursor()
    cursor.execute("select id, title, notes, year, location, nextmuralid, artistKnown from murals inner join artistMuralRelation on murals.id = artistMuralRelation.mural_id where artistMuralRelation.artist_id = %s order by id asc", (id, ))
    murals = cursor.fetchmany(150)
    returnable = []

    for mural in murals:
        returnable.append(handleMuralDBResp(mural))

    return returnable

"""
Get artist details
"""
def getArtistDetails(id):
    cursor = conn.cursor()
    cursor.execute("select id, name, notes from artists where id=%s", (id, ))
    resp = cursor.fetchone()
    return {
            "id":      resp[0],
            "name":    resp[1],
            "notes":   resp[2]
            }

"""
Get mural details
"""
def getMural(id):
    cursor = conn.cursor()
    cursor.execute("select id, title, notes, year, location, nextmuralid, artistKnown, active from murals where id = %s", (id, ))
    dbResp = cursor.fetchone()

    if dbResp == None:
        logging.warning("DB Response was None")
        logging.warning("ID was '{0}'".format(id))
        return None

    muralInfo = handleMuralDBResp(dbResp)

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
    cursor = conn.cursor()
    cursor.execute("select murals.id, murals.title, murals.notes, murals.year, murals.location, murals.nextmuralid, murals.artistKnown from mural_tags join tags on mural_tags.tag_id = tags.id join murals on murals.id = mural_tags.mural_id where name = %s", (tag, ))
    resp = cursor.fetchall()

    returnable = []

    for mural in resp:
        returnable.append(handleMuralDBResp(mural))

    return returnable

"""
Get all tags / Get all tags on certain mural
(logic based on whether mural_id is passed in)
"""
def getTags(mural_id=None):
    cursor = conn.cursor()
    if (mural_id==None):
        cursor.execute("select name from tags")
    else:
        cursor.execute("select tags.name from mural_tags join tags on tags.id=mural_tags.tag_id where mural_id = %s", (mural_id, ))

    return [i[0] for i in cursor.fetchall()]

"""
Get all artist IDs
"""
def getAllArtists():
    cursor = conn.cursor()
    cursor.execute("select id from artists")
    resp = cursor.fetchall()

    returnable = []

    for id in resp:
        returnable.append(getArtistDetails(id[0]))

    return returnable

"""
Get a random assortment of images from DB, excluding thumbnails
"""
def getRandomImages(count):
    returnable = []
    cursor = conn.cursor()

    cursor.execute("select images.imghash as imghash, images.ordering as ordering, images.caption AS caption, images.alttext AS alttext, images.id as id from images left join imageMuralRelation on images.id = imageMuralRelation.image_id where images.ordering != 0")
    images = cursor.fetchall()

    if (images != None):
        for image in images:
            returnable.append({"imgurl":get_file_s3(s3_bucket,image[0]),"ordering":image[1],"caption":image[2],"alttext":image[3], "id":image[4]})

    shuffle(returnable)

    return returnable[:8]

########################
#
#   Pages
#
########################

@app.route("/")
def home():
    return render_template("home.html", pageTitle="RIT's Overlooked Art Museum", muralHighlights=getRandomImages(0))

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
        return render_template("catalog.html", q=query, murals=searchMurals(query))

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
        print("No page")
        return render_template("404.html"), 404
    else:
        return render_template("paginated.html", page=(page+1), murals=getMuralsPaginated(page))

"""
Page for specific mural details
"""
@app.route("/murals/<id>")
def mural(id):
    if (checkMuralExists(id)):
        return render_template("mural.html", muralDetails=getMural(id), tags=getTags(id))
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

"""
Delete artist and all relations from DB
"""
def deleteArtistGivenID(id):
    curs = conn.cursor()

    curs.execute("delete from artistmuralrelation where artist_id = %s", (id, ))
    curs.execute("delete from artists where id = %s", (id, ))

    conn.commit()

"""
Delete mural entry, all relations, and all images from DB and S3
"""
def deleteMuralEntry(id):
    curs = conn.cursor()

    # Get all images relating to this mural from the DB
    curs.execute("select images.imghash as imghash, images.id as id from images left join imageMuralRelation on images.id = imageMuralRelation.image_id where imageMuralRelation.mural_id = %s;", (id, ))
    # images = [(imghash, id), ...]
    images = curs.fetchmany(150)

    for image in images:
        remove_file(s3_bucket, image[0])
        curs.execute("delete from images where id=%s", (image[1], ))
    
    curs.execute("delete from imagemuralrelation where mural_id = %s", (id, ))
    curs.execute("delete from artistmuralrelation where mural_id = %s", (id, ))
    curs.execute("delete from murals where id = %s", (id, ))

    conn.commit()

"""
Upload fullsize and resized image, add relation to mural given ID
"""
def uploadImageResize(file, mural_id, count):
    curs = conn.cursor()
    fullsizehash = hashlib.md5(file.read()).hexdigest()
    file.seek(0)

    # Upload full size img to S3
    upload_file(s3_bucket, fullsizehash, file)

    curs.execute("insert into images (fullsizehash, ordering) values (%s, %s) returning id", (fullsizehash, count))
    img_id = curs.fetchone()[0]

    with Image.open(file) as im:
        width = (im.width * app.config["MAX_IMG_HEIGHT"]) // im.height

        (width, height) = (width, app.config["MAX_IMG_HEIGHT"])
        print(width, height)
        im = im.resize((width,height))

        im = im.convert("RGB")
        im.save(fullsizehash + ".resized", "JPEG")

    with open((fullsizehash + ".resized"), "rb") as rs:

        file_hash = hashlib.md5(rs.read()).hexdigest()
        rs.seek(0)
        
        upload_file(s3_bucket, file_hash, rs, filename=fullsizehash+".resized")

        print(get_file_s3(s3_bucket, file_hash))

        curs.execute("update images set imghash = %s, ordering = %s where id = %s", (file_hash, count, img_id))

    curs.execute("insert into imageMuralRelation (image_id, mural_id) values (%s, %s)", (img_id, mural_id))

    conn.commit()

########################
#   Pages
########################

"""
Route to edit mural page
"""
@app.route('/edit/<id>')
@debug_only
def edit(id):
    return render_template("edit.html", muralDetails=getMural(id))

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
    print(request.form)

    curs = conn.cursor()

    dt = datetime.now(timezone.utc)

    curs.execute("insert into feedback (notes, time, mural_id) values (%s, %s, %s);", (request.form["notes"], str(dt) ,request.form["muralid"]))

    conn.commit()
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
Route to edit image details
Set caption and alttext based on http form
"""
@app.route('/editimage/<id>', methods=["POST"])
@debug_only
def editImage(id):
    curs = conn.cursor()

    curs.execute("update images set caption = %s, alttext = %s where id = %s", (request.form["caption"],request.form["alttext"],id))

    conn.commit()
    return ('', 204)

"""
Route to delete image
"""
@app.route('/deleteimage/<id>', methods=["POST"])
@debug_only
def deleteImage(id):
    curs = conn.cursor()
    curs.execute("select images.imghash as imghash from images left join imageMuralRelation on images.id = imageMuralRelation.image_id where imageMuralRelation.image_id = %s;", (id, ))
    images = curs.fetchmany(150)

    for image in images:
        remove_file(s3_bucket, image[0])
    curs.execute("delete from imagemuralrelation where image_id = %s", (id, ))
    conn.commit()

    return redirect("/edit/")

"""
Route to upload new image
"""
@app.route("/uploadimage/<id>", methods=["POST"])
@debug_only
def uploadNewImage(id):
    curs = conn.cursor()
    curs.execute("select count(*) from imageMuralRelation where mural_id = %s", (id, ))
    count = int(curs.fetchone()[0])

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
    curs = conn.cursor()

    artistKnown = True if request.form.get('artistknown','on') else False
    if not (request.form["year"].isdigit()):
        return render_template("404.html"), 404

    curs.execute("insert into murals (title, artistKnown, notes, year, location) values (%s, %s, %s, %s, %s) returning id;",(request.form["title"],artistKnown,request.form["notes"], request.form["year"], request.form["location"]))
    mural_id = curs.fetchone()[0]

    # Count is the order in which the images are shown
    #   0 is the thumbnail (only shown on mural card)
    #   All other values denote the order shown in the image carousel
    count = 0
    for f in request.files.items(multi=True):
        filename = secure_filename(f[1].filename)
        print(f[1].filename)

        fullsizehash = hashlib.md5(f[1].read()).hexdigest()
        f[1].seek(0)

        # Check if image is already used in DB
        curs.execute("select count(*) from images where imghash = %s",(fullsizehash, ))
        if (int(curs.fetchone()[0]) > 0):
            print(fullsizehash)
            return render_template("404.html"), 404
        
        # Begin creating thumbnail version
        if count == 0:
            with open(fullsizehash, 'wb') as file:
                f[1].seek(0)
                f[1].save(file)

            with Image.open(fullsizehash) as im:
                if (im.width == 256 or im.height == 256):
                    # Already a thumbnail
                    print("Already a thumbnail...")
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
                curs.execute("insert into images (imghash, ordering) values (%s, %s) returning id", (file_hash, 0))
                image_id = curs.fetchone()[0]
                curs.execute("insert into imageMuralRelation (image_id, mural_id) values (%s, %s)", (image_id,mural_id))

            conn.commit()
            count += 1

        # Begin adding full size to database
    
        f[1].seek(0)

        uploadImageResize(f[1], mural_id, count)

        count += 1

    if (artistKnown):
        artists = request.form["artists"].split(',')
        for artist in artists:
            curs.execute("select count(*) from artists where name = %s", (artist, ))
            if(int(curs.fetchone()[0]) > 0):
                curs.execute("select id from artists where name = %s", (artist,))
            else:
                curs.execute("insert into artists (name) values (%s) returning id", (artist, ))

            artist_id = curs.fetchone()[0]

            curs.execute("insert into artistMuralRelation (artist_id, mural_id) values (%s ,%s)", (artist_id,mural_id))

    conn.commit()

    return redirect("/edit/{0}".format(mural_id))

if __name__ == "__main__":
    try:
        if not app.config["DEBUG"]:
            app.run(host="0.0.0.0", port=8080)
        else:
            app.run()
    finally:
        conn.close()