import os
import subprocess
from flask import Flask, render_template, request, redirect
import psycopg2
import logging
from werkzeug.utils import secure_filename
import hashlib
from s3 import get_bucket, get_file_s3, upload_file, remove_file, get_file_list

app = Flask(__name__)
logging.info("Starting up...")

if os.path.exists(os.path.join(os.getcwd(), "config.py")):
    app.config.from_pyfile(os.path.join(os.getcwd(), "config.py"))
else:
    app.config.from_pyfile(os.path.join(os.getcwd(), "config.env.py"))

git_cmd = ['git', 'rev-parse', '--short', 'HEAD']
app.config["GIT_REVISION"] = subprocess.check_output(git_cmd).decode('utf-8').rstrip()

logging.info("Connecting to S3 Bucket {0}".format(app.config["BUCKET_NAME"]))
s3_bucket = get_bucket(app.config["S3_URL"], app.config["S3_KEY"], app.config["S3_SECRET"], app.config["BUCKET_NAME"])

files = get_file_list(s3_bucket)

logging.info("Connecting to DB {0}".format(app.config["DBNAME"]))
conn = psycopg2.connect(**{
        "database": app.config["DBNAME"],
        "user": app.config["DBUSER"],
        "password": app.config["DBPWD"],
        "host": app.config["DBHOST"],
        "port": app.config["DBPORT"]
    })

def getAllMurals(cursor):
    cursor.execute("select id, title, notes, year, location, nextmuralid, artistKnown from murals order by id asc")
    murals = cursor.fetchmany(150)
    returnable = []

    for mural in murals:
        returnable.append(handleMuralDBResp(cursor, mural))

    return returnable

def getAllMuralsFromYear(cursor, year):
    cursor.execute("select id, title, notes, year, location, nextmuralid, artistKnown from murals where year = {0} order by id asc".format(year))
    murals = cursor.fetchmany(150)
    returnable = []

    for mural in murals:
        returnable.append(handleMuralDBResp(cursor, mural))

    return returnable

def getAllMuralsFromArtist(cursor, id):
    cursor.execute("select id, title, notes, year, location, nextmuralid, artistKnown from murals inner join artistMuralRelation on murals.id = artistMuralRelation.mural_id where artistMuralRelation.artist_id = {0} order by id asc".format(id))
    murals = cursor.fetchmany(150)
    returnable = []

    for mural in murals:
        returnable.append(handleMuralDBResp(cursor, mural))

    return returnable

def getArtistDetails(cursor, id):
    cursor.execute("select id, name, notes from artists where id={0}".format(id[0]))
    resp = cursor.fetchone()
    return {
            "id":      resp[0],
            "name":    resp[1],
            "notes":   resp[2]
            }

def getMural(cursor, id):
    cursor.execute("select id, title, notes, year, location, nextmuralid, artistKnown from murals where id = {0}".format(id))
    dbResp = cursor.fetchone()

    if dbResp == None:
        logging.warning("DB Response was None")
        logging.warning("ID was '{0}'".format(id))
        return None

    muralInfo = handleMuralDBResp(cursor, dbResp)

    logging.debug(muralInfo)        
    return muralInfo

def handleMuralDBResp(cursor, dbResp):
    muralInfo = {
        "id":  0,
        "title": "",
        "year": 0,
        "location": "",
        "notes": "",
        "prevmuralid": None,
        "nextmuralid": None,
        "primaryimage": "",
        "artists": [],
        "images": []
    }

    artists = []

    if dbResp[6] == True:
        cursor.execute("select artists.id AS id, artists.name AS name from artists left join artistMuralRelation on artists.id = artistMuralRelation.artist_id where mural_id = {0}".format(dbResp[0]))
        artists = cursor.fetchall()

    cursor.execute("select id from murals where nextmuralid = {0}".format(dbResp[0]))
    prevmuralid = cursor.fetchone()

    muralInfo["id"] = dbResp[0]
    muralInfo["title"] = dbResp[1]
    muralInfo["notes"] = dbResp[2]
    muralInfo["year"] = dbResp[3]
    muralInfo["location"] = dbResp[4]
    if ((prevmuralid != None) and (len(prevmuralid) > 0)):
        muralInfo["prevmuralid"] = prevmuralid[0]
    muralInfo["nextmuralid"] = dbResp[5]

    cursor.execute("select images.imghash as imghash, images.ordering as ordering, images.caption AS caption, images.alttext AS alttext, images.id as id from images left join imageMuralRelation on images.id = imageMuralRelation.image_id where imageMuralRelation.mural_id = {0};".format(dbResp[0]))
    images = cursor.fetchall()

    if (images != None):
        for image in images:
            if image[1] == 0:
                muralInfo["primaryimage"] = get_file_s3(s3_bucket,image[0])
            muralInfo["images"].append({"imgurl":get_file_s3(s3_bucket,image[0]),"ordering":image[1],"caption":image[2],"alttext":image[3], "id":image[4]})

    for artist in artists:
        muralInfo["artists"].append({"name":artist[1],"id":artist[0]})

    return muralInfo

def checkYearExists(cursor, year):
    if not year.isdigit():
        return None
    
    return True

def checkArtistExists(cursor, id):
    if not id.isdigit():
        return None
    
    return True

def checkMuralExists(cursor, id):
    # Check id is not bad
    if not id.isdigit():
        return None

    return True

def getAllArtists(cursor):
    cursor.execute("select id from artists")
    resp = cursor.fetchall()

    returnable = []

    for id in resp:
        returnable.append(getArtistDetails(cursor,id))

    return returnable

def getRandomImages(count):
    returnable = []
    cursor = conn.cursor()

    cursor.execute("select images.imghash as imghash, images.ordering as ordering, images.caption AS caption, images.alttext AS alttext, images.id as id from images left join imageMuralRelation on images.id = imageMuralRelation.image_id where imageMuralRelation.mural_id > 3")
    images = cursor.fetchall()

    if (images != None):
        for image in images:
            returnable.append({"imgurl":get_file_s3(s3_bucket,image[0]),"ordering":image[1],"caption":image[2],"alttext":image[3], "id":image[4]})

    return returnable

@app.route("/")
def home():
    return render_template("home.html", pageTitle="Tunnel Vision: RIT's Overlooked Art Museum", muralHighlights=getRandomImages(0),murals=getAllMurals(conn.cursor()))

@app.route("/murals/<id>")
def mural(id):
    if (checkMuralExists(conn.cursor(), id)):
        return render_template("mural.html", muralDetails=getMural(conn.cursor(), id))
    else:
        return render_template("404.html")
    
@app.route("/artist/<id>")
def artist(id):
    if (checkArtistExists(conn.cursor(), id)):
        return render_template("filtered.html", pageTitle="Artist Search", subHeading=getArtistDetails(conn.cursor(), id), murals=getAllMuralsFromArtist(conn.cursor(), id))
    else:
        return render_template("404.html")
    
@app.route("/year/<year>")
def year(year):
    if (checkYearExists(conn.cursor(), year)):
        return render_template("filtered.html", pageTitle="Murals from {0}".format(year), subHeading=None, murals=getAllMuralsFromYear(conn.cursor(), year))
    else:
        return render_template("404.html")
    
@app.route('/edit/<id>')
def edit(id):
    return render_template("edit.html", muralDetails=getMural(conn.cursor(), id))

@app.route('/about')
def about():
    return render_template("about.html", muralHighlights=getRandomImages(0))

@app.route('/deleteArtist/<id>', methods=["POST"])
def deleteArtist(id):
    if checkArtistExists(conn.cursor(), id):
        curs = conn.cursor()

        curs.execute("delete from artistmuralrelation where artist_id = {0}".format(id))
        curs.execute("delete from artists where id = {0}".format(id))

        conn.commit()

        return ('', 204)
    else:
        return render_template("404.html")

@app.route('/delete/<id>', methods=["POST"])
def delete(id):
    if checkMuralExists(conn.cursor(), id):
        curs = conn.cursor()
        curs.execute("select images.imghash as imghash, images.id as id from images left join imageMuralRelation on images.id = imageMuralRelation.image_id where imageMuralRelation.mural_id = {0};".format(id))
        images = curs.fetchmany(150)

        for image in images:
            remove_file(s3_bucket, image[0])
            curs.execute("delete from images where id='{0}'".format(image[1]))
        
        curs.execute("delete from imagemuralrelation where mural_id = {0}".format(id))

        curs.execute("delete from artistmuralrelation where mural_id = {0}".format(id))

        curs.execute("delete from murals where id = {0}".format(id))
        conn.commit()
        return ('', 204)
    else:
        return render_template("404.html")
    
@app.route('/editimage/<id>', methods=["POST"])
def editImage(id):
    curs = conn.cursor()

    curs.execute("update images set caption = '{0}', alttext = '{1}' where id = {2}".format(request.form["caption"],request.form["alttext"],id))

    conn.commit()
    return ('', 204)

@app.route('/deleteimage/<id>', methods=["POST"])
def deleteImage(id):
    curs = conn.cursor()
    curs.execute("select images.imghash as imghash from images left join imageMuralRelation on images.id = imageMuralRelation.image_id where imageMuralRelation.image_id = {0};".format(id))
    images = curs.fetchmany(150)

    for image in images:
        remove_file(s3_bucket, image[0])
    curs.execute("delete from imagemuralrelation where image_id = {0}".format(id))
    conn.commit()

    return ('', 204)

def not_found(e):
    return render_template("404.html")

@app.route("/uploadimage/<id>", methods=["POST"])
def uploadNewImage(id):
    curs = conn.cursor()
    count = 0
    for f in request.files.items(multi=True):
        filename = secure_filename(f[1].filename)
        print(f[1].filename)

        file_hash = hashlib.md5(f[1].read()).hexdigest()
        f[1].seek(0)

        curs.execute("select count(*) from images where imghash = '{0}'".format(file_hash))
        if (int(curs.fetchone()[0]) > 0):
            print(file_hash)
            return render_template("404.html")
        
        upload_file(s3_bucket, file_hash, f[1])

        curs.execute("insert into images (imghash, ordering) values ('{0}', {1}) returning id".format(file_hash, count))
        img_id = curs.fetchone()[0]

        curs.execute("insert into imageMuralRelation (image_id, mural_id) values ({0}, {1})".format(img_id,id))

        count += 1

    conn.commit()
    
    return redirect("/edit/{0}".format(id))

@app.route("/upload", methods=["POST"])
def upload():
    print(request.form)
    print(request.files)

    curs = conn.cursor()

    artistKnown = True if request.form.get('artistknown','on') else False
    if not (request.form["year"].isdigit()):
        return render_template("404.html")

    curs.execute("insert into murals (title, artistKnown, notes, year, location) values ('{0}', {1}, '{2}', {3}, '{4}') returning id;".format(request.form["title"],artistKnown,request.form["notes"], request.form["year"], request.form["location"]))
    mural_id = curs.fetchone()[0]

    count = 0
    for f in request.files.items(multi=True):
        filename = secure_filename(f[1].filename)
        print(f[1].filename)

        file_hash = hashlib.md5(f[1].read()).hexdigest()
        f[1].seek(0)

        curs.execute("select count(*) from images where imghash = '{0}'".format(file_hash))
        if (int(curs.fetchone()[0]) > 0):
            print(file_hash)
            return render_template("404.html")
        
        upload_file(s3_bucket, file_hash, f[1])

        curs.execute("insert into images (imghash, ordering) values ('{0}', {1}) returning id".format(file_hash, count))
        img_id = curs.fetchone()[0]

        curs.execute("insert into imageMuralRelation (image_id, mural_id) values ({0}, {1})".format(img_id,mural_id))

        count += 1

    if (artistKnown):
        artists = request.form["artists"].split(',')
        for artist in artists:
            curs.execute("select count(*) from artists where name = '{0}'".format(artist))
            if(int(curs.fetchone()[0]) > 0):
                curs.execute("select id from artists where name = '{0}'".format(artist))
            else:
                curs.execute("insert into artists (name) values ('{0}') returning id".format(artist))

            artist_id = curs.fetchone()[0]

            curs.execute("insert into artistMuralRelation (artist_id, mural_id) values ({0},{1})".format(artist_id,mural_id))

    conn.commit()

    return redirect("/edit/{0}".format(mural_id))

@app.route("/admin")
def admin():
    return render_template("admin.html", murals=getAllMurals(conn.cursor()), artists=getAllArtists(conn.cursor()))

if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", debug=True)
    finally:
        conn.close()