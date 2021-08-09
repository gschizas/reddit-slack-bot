SQL_SURVEY_PREFILLED_ANSWERS = """select answer[3] AS Code, answer_value as Answer, count(*) AS VoteCount
from (select regexp_split_to_array(code, '_') AS answer_parts, *
      from "Answers"
      where  code = 'q_{0}' or code like 'q\_{0}\_%') AS dt(answer)
group by 1, 2
order by 3 desc"""
SQL_SURVEY_TEXT = """select answer_value as Answer, count(*) AS VoteCount 
from "Answers"
where code = 'q_{0}'
group by 1
order by 2 desc"""
SQL_SURVEY_SCALE_MATRIX = """select answer[3] AS AnswerCode, answer_value AS AnswerValue, count(vote_id) AS VoteCount
from (select regexp_split_to_array(code, '_') AS answer_parts, *
      from "Answers"
      where code like 'q\_{0}\_%') AS dt(answer)
group by 1, 2
order by 1, 3 desc"""
SQL_SURVEY_PARTICIPATION = """select count(*), date(datestamp) from "Votes"
group by date(datestamp)
order by date(datestamp);"""
SQL_KUDOS_INSERT = """\
INSERT INTO kudos (
   from_user, from_user_id,
   to_user, to_user_id,
   team_name, team_id,
   channel_name, channel_id,
   permalink, reason)
VALUES (
   %(sender_name)s, %(sender_id)s,
   %(recipient_name)s, %(recipient_id)s, 
   %(team_name)s, %(team_id)s,
   %(channel_name)s, %(channel_id)s,
   %(permalink)s, %(reason)s);
"""
SQL_KUDOS_VIEW = """\
SELECT to_user as "User", COUNT(*) as Kudos
FROM kudos
WHERE DATE_PART('day', NOW() - datestamp) < %(days)s
GROUP BY to_user
ORDER BY 2 DESC;"""
SQL_CHEESE_VIEW = """SELECT "objectData" FROM "machineState" WHERE "machineState"."machineName" = %(machine_name)s;"""
ARCHIVE_URL = 'http://archive.is'
CHROME_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/77.0.3865.90 Safari/537.36')
MAGIC_8_BALL_OUTCOMES = [
    "It is certain.",
    "It is decidedly so.",
    "Without a doubt.",
    "Yes - definitely.",
    "You may rely on it.",
    "As I see it, yes.",
    "Most likely.",
    "Outlook good.",
    "Yes.",
    "Signs point to yes.",
    "Reply hazy, try again.",
    "Ask again later.",
    "Better not tell you now.",
    "Cannot predict now.",
    "Concentrate and ask again.",
    "Don't count on it.",
    "My reply is no.",
    "My sources say no.",
    "Outlook not so good.",
    "Very doubtful."]
DICE_REGEX = r'^(?P<Times>\d{1,2})?d(?P<Sides>\d{1,2})\s*(?:\+\s*(?P<Bonus>\d{1,2}))?$'
WIKI_PAGE_BAD_FORMAT = "Page should have a title (starting with `# `) at the first line and an empty line below that"
MID_DOT: str = '\xb7'
