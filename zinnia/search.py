"""Search module with complex query parsing for Zinnia"""
from django.utils import six

from pyparsing import Word
from pyparsing import alphas
from pyparsing import WordEnd
from pyparsing import Combine
from pyparsing import opAssoc
from pyparsing import Optional
from pyparsing import OneOrMore
from pyparsing import StringEnd
from pyparsing import printables
from pyparsing import quotedString
from pyparsing import removeQuotes
from pyparsing import ParseResults
from pyparsing import CaselessLiteral
from pyparsing import operatorPrecedence

from django.db.models import Q

from zinnia.models.entry import Entry
from zinnia.models.author import Author
from zinnia.settings import STOP_WORDS
from zinnia.settings import SEARCH_FIELDS


def createQ(token):
    """
    Creates the Q() object.
    """
    meta = getattr(token, 'meta', None)
    query = getattr(token, 'query', '')
    wildcards = None

    if isinstance(query, six.string_types):  # Unicode -> Quoted string
        search = query
    else:  # List -> No quoted string (possible wildcards)
        if len(query) == 1:
            search = query[0]
        elif len(query) == 3:
            wildcards = 'BOTH'
            search = query[1]
        elif len(query) == 2:
            if query[0] == '*':
                wildcards = 'START'
                search = query[1]
            else:
                wildcards = 'END'
                search = query[0]

    # Ignore connective words (of, a, an...) and STOP_WORDS
    if (len(search) < 3 and not search.isdigit()) or search in STOP_WORDS:
        return Q()

    if not meta:
        q = Q()
        for field in SEARCH_FIELDS:
            q |= Q(**{'%s__icontains' % field: search})
        return q

    if meta == 'category':
        if wildcards == 'BOTH':
            return (Q(categories__title__icontains=search) |
                    Q(categories__slug__icontains=search))
        elif wildcards == 'START':
            return (Q(categories__title__iendswith=search) |
                    Q(categories__slug__iendswith=search))
        elif wildcards == 'END':
            return (Q(categories__title__istartswith=search) |
                    Q(categories__slug__istartswith=search))
        else:
            return (Q(categories__title__iexact=search) |
                    Q(categories__slug__iexact=search))
    elif meta == 'author':
        if wildcards == 'BOTH':
            return Q(**{'authors__%s__icontains' % Author.USERNAME_FIELD:
                        search})
        elif wildcards == 'START':
            return Q(**{'authors__%s__iendswith' % Author.USERNAME_FIELD:
                        search})
        elif wildcards == 'END':
            return Q(**{'authors__%s__istartswith' % Author.USERNAME_FIELD:
                        search})
        else:
            return Q(**{'authors__%s__iexact' % Author.USERNAME_FIELD:
                        search})
    elif meta == 'tag':  # TODO: tags ignore wildcards
        return Q(tags__icontains=search)


def unionQ(token):
    """
    Appends all the Q() objects.
    """
    query = Q()
    operation = 'and'
    negation = False

    for t in token:
        if type(t) is ParseResults:  # See tokens recursively
            query &= unionQ(t)
        else:
            if t in ('or', 'and'):  # Set the new op and go to next token
                operation = t
            elif t == '-':  # Next tokens needs to be negated
                negation = True
            else:  # Append to query the token
                if negation:
                    t = ~t
                if operation == 'or':
                    query |= t
                else:
                    query &= t
    return query


NO_BRTS = printables.replace('(', '').replace(')', '')
SINGLE = Word(NO_BRTS.replace('*', ''))
WILDCARDS = Optional('*') + SINGLE + Optional('*') + WordEnd(wordChars=NO_BRTS)
QUOTED = quotedString.setParseAction(removeQuotes)

OPER_AND = CaselessLiteral('and')
OPER_OR = CaselessLiteral('or')
OPER_NOT = '-'

TERM = Combine(Optional(Word(alphas).setResultsName('meta') + ':') +
               (QUOTED.setResultsName('query') |
                WILDCARDS.setResultsName('query')))
TERM.setParseAction(createQ)

EXPRESSION = operatorPrecedence(TERM, [
    (OPER_NOT, 1, opAssoc.RIGHT),
    (OPER_OR, 2, opAssoc.LEFT),
    (Optional(OPER_AND, default='and'), 2, opAssoc.LEFT)])
EXPRESSION.setParseAction(unionQ)

QUERY = OneOrMore(EXPRESSION) + StringEnd()
QUERY.setParseAction(unionQ)


def advanced_search(pattern):
    """
    Parse the grammar of a pattern and build a queryset with it.
    """
    query_parsed = QUERY.parseString(pattern)
    return Entry.published.filter(query_parsed[0]).distinct()
