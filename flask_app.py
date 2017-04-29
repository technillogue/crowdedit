# -*- coding: utf-8 -*-
from flask import Flask, session, redirect, render_template, request, url_for
from sqlalchemy import *
import sqlalchemy.sql
import sqlalchemy
#from flask_sqlalchemy import SQLAlchemy
import datetime, sys
from collections import Counter
from random import choice

app = Flask(__name__)
app.config["DEBUG"] = True


# SQL stuff:
metadata = MetaData()
snippets = Table("snippets", metadata,
    Column("id", Integer, primary_key=True),
    Column("text", Text, nullable=False, default="")
)
votes = Table("votes", metadata,
    Column("id", Integer, primary_key=True),
    Column("snippet_id", Integer, nullable=False, index=True),
    Column("positive", Boolean, nullable=False, index=True),
    Column("votername", String(128), index=True),
    Column("created_at", Date, default=datetime.datetime.now),
    Column("updated_at", Date, onupdate=datetime.datetime.now),
    Column("approximate_user_identifier", String(128))
)

comments = Table("comments", metadata,
    Column("id", Integer, primary_key=True),
    Column("snippet_id", Integer, nullable=False, index=True),
    Column("votername", String(128), index=True),
    Column("created_at", Date, default=datetime.datetime.now),
    Column("text", Text, nullable=False, default="")
)


SQLALCHEMY_DATABASE_URI = "mysql+mysqlconnector://{username}:{password}@{hostname}/{databasename}".format(
    username="enbug",
    password="rqnyfdztwutldbkwvhwk",
    hostname="enbug.mysql.pythonanywhere-services.com",
    databasename="enbug$project",
)
#app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
#app.config["SQLALCHEMY_POOL_RECYCLE"] = 100

engine = create_engine(SQLALCHEMY_DATABASE_URI)
metadata.create_all(engine)

#db = SQLAlchemy(app)
#from flask_app import db
#db.create_all()
#conn = engine.connect()

app.secret_key = 'gbxtqmypswnohyatyulm'

#todo:
# - only show undownvoted snippets
# - don't show the same snippet twice to the same person
# - ask for a name to sign the votes with

@app.route("/name", methods=["POST"])
def name():
    session['name'] = request.form["name"]
    return redirect(url_for('index'))

@app.route("/", methods=["GET", "POST"])
def index():
    if 'name' not in session:
        return render_template("name.html")
    conn = engine.connect()
    if request.method == "GET":
        query = sqlalchemy.sql.text('''SELECT * FROM snippets WHERE NOT EXISTS
            (SELECT * FROM votes WHERE
               (votes.snippet_id = snippets.id
               AND (votes.positive=0 OR votes.votername = :name)));''')
        snippets_to_vote_on = list(conn.execute(query, name=session['name']))
        if len(snippets_to_vote_on) == 0:
            return '<p>all of the snippets have been voted on!</p>'
        snippet = choice(snippets_to_vote_on)
        ##  stats
        totalvotes = list(conn.execute("SELECT COUNT(*) FROM votes"))[0][0]
        voteless = list(conn.execute(
            """SELECT COUNT(*) FROM snippets WHERE NOT EXISTS
            (SELECT * FROM votes where (votes.snippet_id = snippets.id))""")
            )[0][0]
        upvotes = str(float(list(conn.execute(
            "SELECT SUM(positive) FROM votes"))[0][0])*100/totalvotes
            ) + "%"
        yourvotes = Counter(
            item[0] for item in conn.execute(
                sqlalchemy.sql.text(
                        "SELECT positive FROM votes WHERE votername = :name"),
                        name=session['name'])
                )

        yourvotes = "you, {}, have voted {} yep, {} nop - {}% positivity".format(
            session['name'],
            yourvotes[1],
            yourvotes[0],
            100*float(yourvotes[1])/len(yourvotes) if yourvotes else "n/a"
        )
        conn.close()
        return render_template("main.html", passage=snippet.text, id=snippet.id, totalvotes=totalvotes, unvoted=voteless, upvotes=upvotes, yourvotes=yourvotes)
    vote = (request.form["vote"] == "True")
    snippet_id = request.form["snippet_id"]
    sys.stderr.write("hi {} {}".format(vote, snippet_id))
    ins = votes.insert().values(snippet_id=snippet_id, positive=vote, votername = session['name'])
    conn.execute(ins)
    comment = request.form["comment"]
    if comment:
        ins = comments.insert().values(snippet_id=snippet_id, votername=session['name'], text=comment)
        conn.execute(ins)
    conn.close()
    return redirect(url_for('index'))


@app.route("/addsnippet", methods=["GET", "POST"])
def addsnippet():
    if request.method == "GET":
        return render_template("addsnippet.html")
    #ins = snippets.insert().values(text = request.args.get("text"))
    conn = engine.connect()
    for section in request.form["text"].split("%["):
        title, section = section.split("\n", 1)
        sys.stderr.write(title)
        for snippet in section.split("%split%"):
            snippet = snippet.strip() + "\n[day " + title + "]"
            ins = snippets.insert().values(text = snippet)
            conn.execute(ins)
    conn.close()
    return redirect(url_for('index'))

@app.route("/admin")
def admin():
    query = "SELECT * FROM snippets JOIN votes ON snippets.id = votes.snippet_id"
    conn = engine.connect()
    votes = conn.execute(query)

    comments = list(conn.execute("""SELECT snippets.text AS passage, comments.text AS comment, comments.votername AS author FROM
                    snippets JOIN comments ON snippets.id = comments.snippet_id"""))
    conn.close()
    return render_template("admin.html", votes=votes, comments=comments)

def splitstuff():
    for section in open("shitpostsfinal.txt").read().split("%["):
        if section:
            title, section = section.split("\n", 1)
            sys.stderr.write(title)
            for snippet in section.split("%split%"):
                snippet = snippet.strip() + "\n[day " + title + "]"
                ins = snippets.insert().values(text = snippet)
                conn.execute(ins)