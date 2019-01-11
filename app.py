# -*- coding: utf-8 -*-
import datetime
import sys
import re
import json
from collections import Counter
from random import shuffle, randint
from flask import Flask, session, redirect, render_template, request, url_for, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import and_, or_, not_, exists, alias, case, func, cast


# for updating activity_count after manually changing votes or comments:
#UPDATE public.user SET activity_count = (select count(*) from vote where vote.user_id = "user".id) + (select count(*) from comment where comment.user_id="user".id);

# TODOs:
# - finish output
# - export/import
# - admin
# - editing (with edited_at)
# - alter weights to favor less extreme voters

IMPORTANT_NAMES = [
    u"Guillaume Morrissette",
    u"Emily CA",
    u"Rhiannon Collett",
    u"André",
    u"Klara Du Plessis",
    u"blare coughlin"
]

SNIPPET_PLACEMENT = {
    2855: "early",
    2847: "early",
    3580: "late",
    3578: "end"
}


app = Flask(__name__)
app.config["DEBUG"] = True

if app.config["DEBUG"]:
    from pprint import pprint as pp

SQLALCHEMY_DATABASE_URI = "postgres+psycopg2://{username}:{password}@{hostname}/{databasename}".format(
    username="enbug",
    hostname="localhost",
    password="local",
    databasename="postgres",
)
app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_POOL_RECYCLE"] = 10
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class Snippet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text =  db.Column(db.Text, nullable=False)

    def __repr__(self):
        return "<Snippet {} '{}'>".format(
            self.id,
            self.text[:30].replace("\n", " ")
        )

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False, index=True)
    activity_count = db.Column(db.Integer, default=0)

    def __repr__(self):
        return "<User #{}, {}>".format(self.id, self.name)

    def vote(self, valence, snippet_id):
        """
        decides what the weight should be, logs it, adds it to the session,
        but doesn't commit
        """
        weight = 1.8 / (1 + 2**-((self.activity_count - 12)/14))
        # sigmoid function, ranges from 0.6 to 1.8,
        # halfway point of 1.2 when a user has voted 28 times.
        if self.name in IMPORTANT_NAMES:
            weight += 0.5
        vote = Vote(
            valence=valence,
            user_id=self.id,
            snippet_id=snippet_id,
            weight=weight
        )
        db.session.add(vote)
        app.logger.info("user {} voted {} on snippet {}, weight {}".format(
            session["user_name"],
            valence,
            snippet_id,
            weight
        ))
        self.activity_count += 1

    def comment(self, text, snippet_id):
        pass


class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    valence = db.Column(db.Boolean, nullable=False, index=True)
    snippet_id = db.Column(
        db.Integer,
        db.ForeignKey("snippet.id"),
        nullable=False,
        index=True
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )
    weight = db.Column(db.Float, default=1.0)
    created_at = db.Column(db.Date, default=datetime.datetime.now)

    def __repr__(self):
        return "<Vote {}: {} on snippet {} by user {}, weight {}".format(
            self.id,
            "+" if self.valence else "-",
            self.snippet_id,
            self.user_id,
            self.weight
        )

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.Date, default=datetime.datetime.now)
    snippet_id = db.Column(
        db.Integer,
        db.ForeignKey("snippet.id"),
        nullable=False,
        index=True
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )

    def __repr__(self):
        return "<Comment {}: {} on snippet {} by user {}".format(
            self.id,
            self.text[:30].replace("\n", ""),
            self.snippet_id,
            self.user_id
        )

db.create_all()

app.secret_key = 'this is unnecessary'
# we don't validate the user's identity in any way
# they are therefore welcome to tamper with cookie as much as they want


@app.route("/add_snippet", methods=["GET", "POST"])
def add_snippet():
    """
    expects something like "%[title]%\nfirst snippet\n%split%second snippet.."
    works for one snippet as well.
    """
    if request.method == "GET":
        return render_template("add_snippet.html")
    added_snippets = 0
    for section in request.form["text"].split("%["):
        if section:
            if "]%" in section:
                title, section = section.split("]%")
                title = title.strip()
                section.section.strip()
                app.logger.info(title)
            else:
                title = ""
            for text in section.split("%split%"):
                snippet = Snippet(text="{}\n[{}]".format(text.strip(), title))
                db.session.add(snippet)
                added_snippets += 1
                app.logger.info("added snippet!")
    db.session.commit()
    return redirect(url_for("add_snippet") + "?were_added=%s" % added_snippets)


@app.route("/name", methods=["POST"])
def name():
    """
    fills session["user_name"] and session["user_id"], raises an exception if
    there are multiple users with one name.
    current behavior is to assume that everyone is who they claim to be
    and a new user inputting the same username is actually the previous user
    """
    session["user_name"] = request.form["name"]
    name_count = User.query.filter(User.name == session["user_name"]).count()
    if name_count == 0:
        user = User(name=session["user_name"])
        db.session.add(user)
        db.session.commit()
        app.logger.info("new user: {}".format(repr(user)))
    elif name_count == 1:
        user = User.query.filter(User.name == session["user_name"]).one()
        app.logger.info("found user {}".format(repr(user)))
    else:
        raise Exception("can't have more than one user with the same name rn")
    session["user_id"] = user.id
    return redirect(url_for('index'))

@app.route("/debug")
def debug():
    raise Exception


@app.route("/", methods=["GET", "POST"])
def index():
    """
    on GET selects a snippet for the user to vote on and generates stats;
    on POST enters the vote.
    """
    if "user_name" not in session: # refactor as user_id
        return render_template("name.html")
    current_user = User.query.get(session["user_id"])
    if request.method == "GET":
        # the most common version of this query goes
        #SELECT snippet.id
        #FROM snippet
        #LEFT OUTER JOIN vote AS personal on personal.snippet_id = snippet.id AND personal.user_id=1
        #JOIN vote ON vote.snippet_id = snippet.id
        #WHERE personal.id IS NULL
        #GROUP BY snippet.id
        #ORDER BY sum(vote.weight);
        query = Snippet.query
        if not request.args.get("repeat_vote", "") == "1":
            query = query.filter(
                ~exists().where(
                    and_(
                        Vote.snippet_id == Snippet.id,
                        Vote.user_id == current_user.id
                    )
                ).label("votes")
            )
        if request.args.get("random_order", "") == "1":
            query = query.order_by(func.random())
        else:
            vote_alias = alias(Vote, name="vote_alias")
            query = query.outerjoin(vote_alias).group_by(Snippet.id).order_by(
                func.sum(vote_alias.weight)
                )
        if app.config["DEBUG"]:
            expected_snippets = (
                Snippet.query.count()
                - Vote.query.filter(Vote.user_id==current_user.id).count()
            )
            actual_snippets = query.count()
            app.logger.info("expected {}, actually {}".format(
                expected_snippets,
                actual_snippets
            ))
            assert (actual_snippets == expected_snippets)

        snippet = query.first()
        if snippet is None:
            return "<p> you have voted on every snippet! </p>"
        app.logger.info(
            "for user {} '{}', selected snippet {} out of {} remaining".format(
                current_user.id,
                current_user.name,
                snippet.id,
                query.count()
            )
        )
        average_activity = User.query.with_entities(
                func.sum(User.activity_count)
            ).scalar() / float(User.query.count())
        yep_count = Vote.query.filter(
                Vote.user_id==current_user.id,
                Vote.valence==True
            ).count()
        nop_count = Vote.query.filter(
                Vote.user_id==current_user.id,
                Vote.valence==False
            ).count()
        if nop_count:
            positivity = int(100 * yep_count / float(yep_count + nop_count))
        else:
            positivity = "n/a"
        stats = [
            "you, user #{}, {}, have voted and commented {} times".format(
                    current_user.id,
                    current_user.name,
                    current_user.activity_count
                ),
            "the average user has voted and commented {} times".format(
                    average_activity
                ),
            "you have voted {} yep and {} nop, {}% positivity".format(
                    yep_count,
                    nop_count,
                    positivity
                ),
            "{} snippets that you can vote on remain".format(
                    query.count()
                ),
        ]
        return render_template(
            "main.html",
            passage=snippet.text,
            id=snippet.id,
            stats=stats
        )
    valence = (request.form["vote"] == "True")
    snippet_id = request.form["snippet_id"]

    current_user.vote(valence, snippet_id)
    comment_text = request.form["comment"]
    if comment_text:
        current_user.comment(comment_text, snippet_id)
        comment = Comment(
            snippet_id=snippet_id,
            user_id=current_user.id,
            text=comment_text
        )
    db.session.commit()
    return redirect(url_for('index'))



@app.route("/best")
def best():
    score_threshold = request.args.get("score_threshold", 0)
    show_scores = request.args.get("show_scores", False)
    wordcount_goal = int(request.args.get("wordcount", 10000))
    snippets = Snippet.query.with_entities(
        Snippet.text,
        Snippet.id,
        func.sum(
            case({True: Vote.weight, False:-Vote.weight}, value=Vote.valence)
        ).label("score"),
        func.sum(Vote.weight).label("total_weight")
    ).join(Vote).group_by(Snippet.id).order_by("score").all()
    # select up to goal_wc of the best snippets, seperating snippets
    # that should be in specific parts of the output, and rendering the text
    wordcount = 0
    selected_snippets = []
    special_placement = {"start": [], "early": [], "late": [], "end": []}
    while wordcount < wordcount_goal and len(snippets):
        snippet = snippets.pop()
        wordcount += len(snippet.text.split())
        if show_scores:
            text = "{}\n[score: {:.3f}/{:.3f}]".format(
                snippet.text,
                snippet.score,
                snippet.total_weight
            )
        else:
            text = snippet.text
        if snippet.id in SNIPPET_PLACEMENT:
            special_placement[SNIPPET_PLACEMENT[snippet.id]].append(text)
        else:
            selected_snippets.append(text)
    # randomize order, alternating between long and short snippets
    # randomly insert "early" snippets into the first 10% of the output
    # randomly insert "late" snippets into the last 10% of the output
    middle = int(len(selected_snippets)/2)
    sorted_by_length = sorted(
        selected_snippets,
        key = lambda snippet: len(snippet)
    )
    middle_length = len(sorted_by_length[middle])
    shorter = sorted_by_length[:middle]
    longer = sorted_by_length[middle:]
    shuffle(shorter)
    shuffle(longer)
    for dest, snippet in special_placement.items():
        target_length = shorter if len(snippet) < middle_length else longer
        target_index = {
            "start": 0,
            "early": randint(0, int(len(selected_snippets)/10)),
            "late": randint(-int(len(selected_snippets)/10), -1),
            "end": -1
        }[dest]
        target_length.insert(target_index, snippet)
        # this probably doesn't scale great
        # a better approach might be deciding be choosing the indexes of the
        # early and late snippets in advance, then building the output list
        # using while and pop and appending the early/late ones while the
        # list is being built. choosing the indexes correctly so that the
        # shorter/longer cadence is preserved is tricky.
        # `randint(0, len(selected_snippets)/20)*2 + 1 if len(snippet) >
        # meddle_length else 0` might do the trick
        # however, i assume that there are relatively few snippets and
        # this output is generately rarely enough that it would be foolish
        # to write this harder-to-read optimization at this point in time.
    shorter.reverse()
    longer.reverse()
    # preserves order of insertion for more efficent popping
    # easier to read but more expensive than doing the opposite inserts
    output = ["word count: {}".format(wordcount)]
    while shorter or longer:
        try:
            output.append(shorter.pop())
            output.append(longer.pop())
        except IndexError:
            pass
    return render_template("best.html", snippets=output)


@app.route("/new_admin")
def new_admin():
    organize_by = request.args.get("organize_by", "time") # or "snippet"
    positive_vote = Vote.query.with_entities(
        Vote.user_id,
        func.count(Vote.id).label("vote_count")
    ).filter(Vote.valence).group_by(Vote.user_id).subquery()
    all_vote = alias(Vote)
    user_stats = User.query.with_entities(
        User.id,
        User.name,
        User.activity_count,
        (
            cast(
                positive_vote.c.vote_count
                / cast(func.count(all_vote.c.id), db.Float)
                * 100,
                db.Integer
            )
        ).label("positivity")
    ).outerjoin(
        positive_vote,
        positive_vote.c.user_id==User.id
    ).outerjoin(
        all_vote,
        all_vote.c.user_id == User.id
    ).group_by(User.id, positive_vote.c.vote_count).order_by(User.id).all()


    snippets = []
    for snippet in Snippet.query.all():
        snippets.append({
            "text": snippet.text,
            "votes": Vote.query.with_entities(
                    Vote.user_id,
                    User.name.label("user_name"),
                    Vote.valence
                ).join(User).filter(Vote.snippet_id == snippet.id).all(),
            "comments": Comment.query.with_entities(
                    Comment.user_id,
                    User.name.label("user_name"),
                    Comment.text
                ).join(User).filter(Vote.snippet_id == snippet.id).all()
        })

    return render_template(
        "admin.html",
        user_stats = user_stats,
        snippets = snippets
    )


"""
SELECT
    public.user.id,
    public.user.name,
    public.user.activity_count,
    pos.votes/CAST(count(everything.id) as float) AS positivity
FROM
    public.user
LEFT JOIN
    (SELECT
        user_id, COUNT(*) AS votes
    FROM
        vote
    WHERE
        valence=true
    GROUP BY
        user_id) AS pos
ON
    public.user.id = pos.user_id
LEFT JOIN
    vote as everything
ON
    public.user.id=everything.user_id
GROUP BY
    public.user.id, pos.votes
ORDER BY
public.user.id;
"""


@app.route("/admin")
def admin():
    table = request.args.get("table")
    query = "SELECT * FROM snippets JOIN votes ON snippets.id = votes.snippet_id ORDER BY votes.created_at"
    conn = engine.connect()
    try:
        voterstats = ["name;\t\tweight;\t\tvotes;\t\tpositivity;\t\tcomments"] if table else []
        weights = get_weights()
        for voter, weight in sorted(weights.items(), key=lambda x:-x[1]):
            yourvotecount = Counter(
                item[0] for item in conn.execute(
                    sqlalchemy.sql.text(
                            "SELECT valence FROM votes WHERE user = :name"),
                            name=voter)
                    )
            voterstats.append(
                ((lambda *x:";\t\t".join(x)) if table else ("{} - weight {} - has voted {} times, {}% positivty, and commented {} times".format))(
                *map(str, (
                    voter if voter else "adam zachery",
                    weight,
                    sum(yourvotecount.values()),
                    100*float(yourvotecount[1])/sum(yourvotecount.values()) if yourvotecount else "n/a",
                    list(conn.execute(sqlalchemy.sql.text(u"select count(*) from comments where user = :name"), name=voter.encode("utf-8")))[0][0]
                ))
                )
            )
        votes = conn.execute(query)
        comments = list(conn.execute("""SELECT snippets.text AS passage, comments.text AS comment, comments.user AS author FROM
                    snippets JOIN comments ON snippets.id = comments.snippet_id ORDER BY comments.created_at"""))
    finally:
        conn.close()
    return render_template("admin.html", voterstats=voterstats, votes=votes, comments=comments)








@app.route("/updatesnippet", methods=["GET", "POST"])
def updatesnippet():
    conn = engine.connect()
    try:
        if request.method == "GET":
            snippets = conn.execute('''
            SELECT
            snippets.id AS id,
            snippets.text AS text,
            (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id) AS votecount,
            (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.valence = True) AS upvotecount,
            (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.valence = False) AS downvotecount,
            (SELECT COUNT(*) FROM comments WHERE snippets.id = comments.snippet_id) AS commentcount
            FROM snippets
            ORDER BY (upvotecount + commentcount - downvotecount) DESC
            ;''')
            return render_template("updatesnippet.html", snippets = snippets)
        snippetid = int(request.form["id"])
        newtext = request.form["text"]
        conn.execute(sqlalchemy.sql.text(
                            "UPDATE snippets SET text=:text WHERE id=:id"), text=newtext, id=snippetid)
    finally:
        conn.close()
    return redirect(url_for('updatesnippet'))


@app.route("/downloadjson", methods=["GET"])
def downloadjson():
    return Response(jsonize(), mimetype='application/json; charset=utf-8')


@app.route("/addjson", methods=["GET", "POST"])
def addjson():
    if request.method == "GET":
        return render_template("uploadjson.html")
    new_snippets = json.loads(request.form["json"])
    conn = engine.connect()
    try:
        for snippet_id, snippet_text, new_votes, new_comments in new_snippets:
            ins = snippets.insert().values(text=snippet_text)
            sippet_id = conn.execute(ins).inserted_primary_key[0]
            for old_id, user, valence in new_votes:
                conn.execute(votes.insert().values(
                    snippet_id=snippet_id,
                    valence = valence,
                    user = user
                ))
            for old_id, user, comment_text in new_comments:
                conn.execute(comments.insert().values(
                    snippet_id=snippet_id,
                    text = comment_text,
                    user = user
                ))
        return redirect(url_for('addjson') + '?were_updated_count=' + str(len(new_snippets)))
    finally:
        conn.close()

#@app.route("/uploadjson", methods=["GET", "POST"])
#def uploadjson():
#    if request.method == "GET":
#        return render_template("uploadjson.html")
#    snippets = json.loads(request.form["json"])
#    conn = engine.connect()
#    try:
#        updatecount = 0
#        for snippet_id, snippet_text, votes, comments in snippets:
#            snippet_id = newthing[0]
#            updatecount += conn.execute(
#                    sqlalchemy.sql.text(
#                            "UPDATE snippets SET text=:newtext WHERE id=:id AND text != :newtext"),
#                        id=snippet_id, newtext=snippet_text
#                    ).rowcount
#        return redirect(url_for('') + '?were_updated_count=' + str(updatecount))
#    finally:
#        conn.close()

"""
takes [[snippet_id, snippet_text, [[vote_id, user, vote_valence],
...], [comment_id, user, comment], ...]
returns ([snippets], [votes], [comments]
"""

