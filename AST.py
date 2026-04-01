from dataclasses import dataclass, field
from enum import Enum, auto
import tokens
from tokens import Token, Symbol, Keyword, Identifier
from typing import List, Dict, Optional
import expression
from expression import ExprNode

class NodeType(Enum):
    Program     = auto()    
    Block       = auto()    
    Assignment  = auto()    
    FieldDecl   = auto()    
    Return      = auto()    
    Expression  = auto()    
    Store       = auto()    
    Loop        = auto()    
    LoopControl = auto()    

@dataclass
class ASTNode:
    node_type: NodeType
    children: List['ASTNode'] = field(default_factory=list)
    args: List[str] = field(default_factory=list)
    identifier: Optional[str] = None
    expr: Optional[ExprNode] = None  

class ASTParser:
    def __init__(self, tokens_in: List[Token]):
        self.tokens = tokens_in
        self.i = 0
        self.root = ASTNode(NodeType.Program)
        self.stack = [self.root]

    @property
    def current_node(self):
        return self.stack[-1]

    def parse(self) -> ASTNode:
        while self.i < len(self.tokens):
            token = self.tokens[self.i]
            
            # Dynamic Dispatch
            method_name = f"parse_{type(token).__name__}"
            visitor = getattr(self, method_name, self.parse_default)
            visitor(token)
            
        return self.root

    def parse_Symbol(self, token: Symbol):
        if token.value == "[":
            self.parse_store()
        elif token.value == "{":
            block_node = ASTNode(NodeType.Block)
            self.current_node.children.append(block_node)
            self.stack.append(block_node)
            self.i += 1
        elif token.value == "}":
            if len(self.stack) > 1:
                self.stack.pop()
            else:
                raise SyntaxError("Unexpected '}' - Stack underflow")
            self.i += 1
        elif token.value == ";":
            self.i += 1
        else:
            self.parse_default(token)

    def parse_Keyword(self, token: Keyword):
        if token.value == "return":
            ret_node = ASTNode(NodeType.Return)
            self.current_node.children.append(ret_node)
            self.i += 1
            
            expr_tokens = []
            while self.i < len(self.tokens) and self.tokens[self.i] not in (Symbol(";"), Symbol("}")):
                expr_tokens.append(self.tokens[self.i])
                self.i += 1
            
            if expr_tokens:
                expr_tree = expression.parse_expression(expr_tokens)
                ret_node.children.append(ASTNode(NodeType.Expression, expr=expr_tree))
        else:
            self.parse_default(token)

    def parse_Identifier(self, token: Identifier):
        name = token.value
        if self.i + 1 < len(self.tokens):
            next_tok = self.tokens[self.i+1]
            if next_tok == Symbol("="):
                self.parse_assignment(name)
                return
            elif next_tok == Symbol(":"):
                self.parse_colon_syntax(name)
                return
                
        self.parse_default(token)

    def parse_store(self):
        j = self.i + 1
        balance = 1
        while j < len(self.tokens) and balance > 0:
            if self.tokens[j] == Symbol("["): balance += 1
            elif self.tokens[j] == Symbol("]"): balance -= 1
            j += 1
            
        if j < len(self.tokens) and self.tokens[j] == Symbol("="):
            ptr_tokens = self.tokens[self.i+1 : j-1]
            
            store_node = ASTNode(NodeType.Store)
            self.current_node.children.append(store_node)
            
            store_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(ptr_tokens)))
            
            k = j + 1
            val_tokens = []
            while k < len(self.tokens) and self.tokens[k] != Symbol(";"):
                val_tokens.append(self.tokens[k])
                k += 1
                
            store_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(val_tokens)))
            
            self.i = k
        else:
            self.parse_default(self.tokens[self.i])

    def parse_assignment(self, name: str):
        # We peek ahead to see if it's a loop first (assigned to loop syntax)
        if self.i + 2 < len(self.tokens) and self.tokens[self.i+2] == Symbol("["):
            j = self.i + 3
            balance = 1
            while j < len(self.tokens) and balance > 0:
                if self.tokens[j] == Symbol("["): balance += 1
                elif self.tokens[j] == Symbol("]"): balance -= 1
                j += 1
                
            if j < len(self.tokens) and self.tokens[j] == Symbol(":"):
                loop_node = ASTNode(NodeType.Loop, identifier=name)
                self.current_node.children.append(loop_node)
                
                count_toks = self.tokens[self.i+3 : j-1]
                loop_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(count_toks)))
                
                if j + 1 < len(self.tokens) and isinstance(self.tokens[j+1], Identifier):
                    loop_node.args = [self.tokens[j+1].value]
                else:
                    loop_node.args = ["_"]
                    
                block_node = ASTNode(NodeType.Block)
                loop_node.children.append(block_node)
                self.stack.append(block_node)
                
                self.i = j + 2
                if self.i < len(self.tokens) and self.tokens[self.i] == Symbol("{"):
                    self.i += 1
                return

        assign_node = ASTNode(NodeType.Assignment, identifier=name)
        self.current_node.children.append(assign_node)
        self.i += 2 
        
        args = []
        if self.i < len(self.tokens) and self.tokens[self.i] == Symbol("("):
            self.i += 1
            while self.i < len(self.tokens) and self.tokens[self.i] != Symbol(")"):
                if isinstance(self.tokens[self.i], Identifier):
                    args.append(self.tokens[self.i].value)
                self.i += 1
            if self.i < len(self.tokens) and self.tokens[self.i] == Symbol(")"):
                self.i += 1
                
        if self.i < len(self.tokens) and self.tokens[self.i] == Symbol("{"):
            block_node = ASTNode(NodeType.Block)
            block_node.args = args
            assign_node.children.append(block_node)
            self.stack.append(block_node)
            self.i += 1
            return
            
        expr_tokens = []
        while self.i < len(self.tokens) and self.tokens[self.i] != Symbol(";"):
            expr_tokens.append(self.tokens[self.i])
            self.i += 1
            
        if expr_tokens:
            expr_tree = expression.parse_expression(expr_tokens)
            assign_node.children.append(ASTNode(NodeType.Expression, expr=expr_tree))

    def parse_colon_syntax(self, name: str):
        # Allow loops defined via `:` (ex: name : [expr] : var { ... })
        if self.i + 2 < len(self.tokens) and self.tokens[self.i+2] == Symbol("["):
            j = self.i + 3
            balance = 1
            while j < len(self.tokens) and balance > 0:
                if self.tokens[j] == Symbol("["): balance += 1
                elif self.tokens[j] == Symbol("]"): balance -= 1
                j += 1
                
            if j < len(self.tokens) and self.tokens[j] == Symbol(":"):
                loop_node = ASTNode(NodeType.Loop, identifier=name)
                self.current_node.children.append(loop_node)
                
                count_toks = self.tokens[self.i+3 : j-1]
                loop_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(count_toks)))
                
                if j + 1 < len(self.tokens) and isinstance(self.tokens[j+1], Identifier):
                    loop_node.args = [self.tokens[j+1].value]
                else:
                    loop_node.args = ["_"]
                    
                block_node = ASTNode(NodeType.Block)
                loop_node.children.append(block_node)
                self.stack.append(block_node)
                
                self.i = j + 2
                if self.i < len(self.tokens) and self.tokens[self.i] == Symbol("{"):
                    self.i += 1
                return

        k = self.i + 2
        is_control = False
        while k < len(self.tokens) and self.tokens[k] not in (Symbol(";"), Symbol(","), Symbol("}"), Symbol("{")):
            k += 1
        if k < len(self.tokens) and self.tokens[k] == Symbol(";"):
            is_control = True

        if self.current_node.node_type == NodeType.Block and not is_control:
            field_node = ASTNode(NodeType.FieldDecl, identifier=name)
            self.current_node.children.append(field_node)
            self.i += 2
            
            expr_tokens = []
            while self.i < len(self.tokens) and self.tokens[self.i] not in (Symbol(","), Symbol("}")):
                expr_tokens.append(self.tokens[self.i])
                self.i += 1
                
            if expr_tokens:
                expr_tree = expression.parse_expression(expr_tokens)
                field_node.children.append(ASTNode(NodeType.Expression, expr=expr_tree))
                
            if self.i < len(self.tokens) and self.tokens[self.i] == Symbol(","):
                self.i += 1
        else:
            control_node = ASTNode(NodeType.LoopControl, identifier=name)
            self.current_node.children.append(control_node)
            self.i += 2
            
            if self.i < len(self.tokens):
                tok_val = getattr(self.tokens[self.i], "value", "")
                if tok_val in ("next", "end"):
                    control_node.args = [tok_val]
                    self.i += 1
                else:
                    control_node.args = ["expr"]
                    expr_tokens = []
                    while self.i < len(self.tokens) and self.tokens[self.i] != Symbol(";"):
                        expr_tokens.append(self.tokens[self.i])
                        self.i += 1
                    if expr_tokens:
                        expr_tree = expression.parse_expression(expr_tokens)
                        control_node.children.append(ASTNode(NodeType.Expression, expr=expr_tree))

    def parse_default(self, token: Token):
        if token == Symbol(";"):
            self.i += 1
            return
            
        expr_tokens = []
        while self.i < len(self.tokens) and self.tokens[self.i] != Symbol(";"):
            if self.tokens[self.i] == Symbol("}"):
                break
            expr_tokens.append(self.tokens[self.i])
            self.i += 1
            
        if expr_tokens:
            expr_tree = expression.parse_expression(expr_tokens)
            self.current_node.children.append(ASTNode(NodeType.Expression, expr=expr_tree))

def parse(tokens_in: List[Token]) -> ASTNode:
    parser = ASTParser(tokens_in)
    return parser.parse()