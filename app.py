import os
import subprocess
from flask import Flask, render_template, request
import psycopg2
import logging

app = Flask(__name__)

if os.path.exists(os.path.join(os.getcwd(), "config.py")):
    app.config.from_pyfile(os.path.join(os.getcwd(), "config.py"))
else:
    app.config.from_pyfile(os.path.join(os.getcwd(), "config.env.py"))

git_cmd = ['git', 'rev-parse', '--short', 'HEAD']
app.config["GIT_REVISION"] = subprocess.check_output(git_cmd).decode('utf-8').rstrip()

conn = psycopg2.connect(**{
        "database": app.config["DBNAME"],
        "user": app.config["DBUSER"],
        "password": app.config["DBPWD"],
        "host": app.config["DBHOST"],
        "port": app.config["DBPORT"]
    }).cursor()

def getAllMurals(cursor):
    cursor.execute("select id, title, notes, year, location, imageurl, prevmuralid, nextmuralid, artistKnown from murals order by id asc")
    murals = cursor.fetchmany(150)
    returnable = []

    for mural in murals:
        returnable.append(handleMuralDBResp(cursor, mural))

    return returnable

def getAllMuralsFromArtist(cursor, id):
    cursor.execute("select id, title, notes, year, location, imageurl, prevmuralid, nextmuralid, artistKnown from murals inner join artistMuralRelation on murals.id = artistMuralRelation.mural_id where artistMuralRelation.artist_id = {0} order by id asc".format(id))
    murals = cursor.fetchmany(150)
    returnable = []

    for mural in murals:
        returnable.append(handleMuralDBResp(cursor, mural))

    return returnable

def getMural(cursor, id):
    cursor.execute("select id, title, notes, year, location, imageurl, prevmuralid, nextmuralid, artistKnown from murals where id = {0}".format(id))
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
        "imageurl": "",
        "notes": "",
        "prevmuralid": 0,
        "nextmuralid": 0,
        "artists": [
        ]
    }

    artists = []
    print(dbResp[8])

    if dbResp[8] == True:
        cursor.execute("select artists.id AS id, artists.name AS name from artists left join artistMuralRelation on artists.id = artistMuralRelation.artist_id where mural_id = {0}".format(dbResp[0]))
        artists = cursor.fetchall()

    muralInfo["id"] = dbResp[0]
    muralInfo["title"] = dbResp[1]
    muralInfo["notes"] = dbResp[2]
    muralInfo["year"] = dbResp[3]
    muralInfo["location"] = dbResp[4]
    muralInfo["imageurl"] = dbResp[5]
    muralInfo["prevmuralid"] = dbResp[6]
    muralInfo["nextmuralid"] = dbResp[7]
    
    for artist in artists:
        muralInfo["artists"].append({"name":artist[1],"id":artist[0]})

    return muralInfo

def checkArtistExists(cursor, id):
    if not id.isdigit():
        return None
    
    return True

def checkMuralExists(cursor, id):
    # Check id is not bad
    if not id.isdigit():
        return None

    return True

@app.route("/")
def home():
    return render_template("home.html", murals=getAllMurals(conn))

@app.route("/murals/<id>")
def mural(id):
    if (checkMuralExists(conn, id)):
        return render_template("mural.html", muralDetails=getMural(conn, id))
    else:
        return render_template("404.html")
    
@app.route("/artist/<id>")
def artist(id):
    if (checkArtistExists(conn, id)):
        return render_template("artist.html", murals=getAllMuralsFromArtist(conn, id))
    else:
        return render_template("404.html")

def not_found(e):
    return render_template("404.html")

@app.route("/admin")
def admin():
    return render_template("admin.html")

if __name__ == "__main__":
    getAllMurals(conn)
    app.run(host="0.0.0.0", debug=True)