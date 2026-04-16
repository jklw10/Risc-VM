from dataclasses import dataclass
import re

splitchartype = re.compile(r"(==|!=|<=|>=|[*()\^/=\+\-!|&<>\[\]{}:;,])|([0-9]+)|([a-zA-Z_][a-zA-Z0-9_]*)")

def tokenize(text):
    text = re.sub(r'//.*', '', text)
    token_strings = splitchartype.split(text)
    tokens_out = []
    for ts in token_strings:
        if ts is None:
            continue
        if ts.strip() == "":
            continue
        tokens_out.append(from_string(ts))
    return tokens_out

@dataclass(frozen=True)
class Token():
    pass
@dataclass(frozen=True)
class Invalid(Token): 
    info: str
@dataclass(frozen=True)
class Keyword(Token):
    value: str
@dataclass(frozen=True)
class Symbol(Token): 
    value: str
@dataclass(frozen=True)
class Identifier(Token): 
    value: str
@dataclass(frozen=True)
class Value(Token):
    value: int

weight_dict = {
    Symbol("==")  : 0,
    Symbol("!=")  : 0,
    Symbol("<")   : 0,
    Symbol(">")   : 0,
    Symbol("<=")  : 0,
    Symbol(">=")  : 0,
    Symbol("+")   : 1,
    Symbol("-")   : 1,
    Symbol("*")   : 2,
    Symbol("/")   : 2,
    Symbol("^")   : 3,
    Symbol(".")   : 5,
}

def weight(op: Symbol):
    return weight_dict.get(op, 0)

sym_dict = {
    ""  : Symbol("NoOp" ),
    "(" : Symbol("("    ),
    ")" : Symbol(")"    ),
    "[" : Symbol("["    ),
    "==": Symbol("=="   ),
    "!=": Symbol("!="   ),
    "=" : Symbol("="    ),
    "{" : Symbol("{"    ),
    "}" : Symbol("}"    ),
    "]" : Symbol("]"    ),
    "+" : Symbol("+"    ),
    "-" : Symbol("-"    ),
    "*" : Symbol("*"    ),
    "/" : Symbol("/"    ),
    "^" : Symbol("^"    ),
    "!" : Symbol("!"    ),
    "?" : Symbol("?"    ),
    "|" : Symbol("|"    ),
    "&" : Symbol("&"    ),
    "<" : Symbol("<"    ),
    ">" : Symbol(">"    ),
    "<=": Symbol("<="   ),
    ">=": Symbol(">="   ),
    "." : Symbol("."    ),
    "," : Symbol(","    ),
    ":" : Symbol(":"    ),
    ";" : Symbol(";"    ),
    "@" : Symbol("@"    ),
}

key_dict = {
    "alloc"     : Keyword("alloc" ),
    "const"     : Keyword("const" ),
    "null"      : Keyword("null"  ),
    "var"       : Keyword("var"   ),
    #"return"    : Keyword("return"),
    #"break"     : Keyword("break" ),
    #"type"      : Keyword("type"  ),
    #"skip"      : Keyword("skip"  ),
    #"fn"        : Keyword("fn"    ),
}

def from_string(text:str) -> Token:
    if text is None:
        return Invalid("None input")
    if token := sym_dict.get(text):
        return token
    if token := key_dict.get(text):
        return token
    if text.isdigit():
        return Value(int(text))
    return Identifier(text)

def apply_function(token, op):
    if op == Symbol("NoOp"):
        return token
    return op.applyFunction(token.value)
def apply_operator(lhs, op, rhs):
    if op == Symbol("="):
        return lhs.value.set(rhs)
    lhs.operate(rhs)
def operate(lhs, rhs, op):
    match op:
        case Symbol("+"):  return lhs +  rhs    
        case Symbol("-"):  return lhs -  rhs    
        case Symbol("*"):  return lhs *  rhs    
        case Symbol("/"):  return lhs /  rhs    
        case Symbol("**"): return lhs ** rhs    
        case Symbol("<"):  return lhs <  rhs     
        case Symbol("<="): return lhs <= rhs    
        case Symbol(">"):  return lhs >  rhs     
        case Symbol(">="): return lhs >= rhs     
        case Symbol("!="): return lhs != rhs    
        case Symbol("=="): return lhs == rhs    
        case Symbol("|"):  return lhs |  rhs    
        case Symbol("&"):  return lhs &  rhs    
        case _: return None