from dataclasses import dataclass, field
from enum import Enum, auto
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
    arg_constraints: List[List[Token]] = field(default_factory=list) 
    identifier: Optional[str] = None
    expr: Optional[ExprNode] = None   
    is_type: bool = False           

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

    
    def parse_Keyword(self, token: Keyword):
        # const, var, null soon :tm:
        raise SyntaxError("const, var, null are reserved keywords, but un implemented")
        #self.parse_default(token)

    
    def parse_Identifier(self, token: Identifier):
        name = token.value
        if self.i + 1 < len(self.tokens):
            next_tok = self.tokens[self.i+1]
            if next_tok == Symbol("="):
                self.parse_assignment(name)
                return
            elif next_tok == Symbol("["):
                # Detect array/memory store `array[idx] = expr;`
                j = self.i + 1
                balance = 0
                while j < len(self.tokens):
                    if self.tokens[j] == Symbol("["): 
                        balance += 1
                    elif self.tokens[j] == Symbol("]"):
                        balance -= 1
                        if balance == 0: 
                            break
                    j += 1
                if j + 1 < len(self.tokens) and self.tokens[j+1] == Symbol("="):
                    self.parse_array_store(name, j)
                    return
                
        self.parse_default(token)

    def parse_Symbol(self, token: Symbol):
        if token.value == "[":
            self.parse_store()  # Restored for global memory [65000] = x syntax
        elif token.value == "{":
            block_node = ASTNode(NodeType.Block)
            self.current_node.children.append(block_node)
            self.stack.append(block_node)
            self.i += 1
        elif token.value == "}":
            if len(self.stack) > 1:
                popped_node = self.stack.pop()
            else:
                raise SyntaxError("Unexpected '}' - Stack underflow")
            self.i += 1
            
            # Pipeline Logic: Look ahead to map context output ( e.g., `} : result;` )
            if self.i < len(self.tokens) and self.tokens[self.i] == Symbol(":"):
                self.i += 1
                expr_tokens = []
                while self.i < len(self.tokens) and self.tokens[self.i] not in (Symbol(";"), Symbol("}")):
                    expr_tokens.append(self.tokens[self.i])
                    self.i += 1
                
                # Support output / map, but ignore empty "()" return types
                if expr_tokens and not (len(expr_tokens)==2 and expr_tokens[0]==Symbol("(") and expr_tokens[1]==Symbol(")")):
                    ret_node = ASTNode(NodeType.Return)
                    ret_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(expr_tokens)))
                    popped_node.children.append(ret_node)
                else:
                    ret_node = ASTNode(NodeType.Return)
                    popped_node.children.append(ret_node)
                    
        elif token.value == "(":
            # Pipeline Loop Syntax: (start:end)[index] : {
            is_loop = False
            j = self.i
            balance = 0
            colon_idx = -1
            while j < len(self.tokens):
                if self.tokens[j] == Symbol("("): 
                    balance += 1
                elif self.tokens[j] == Symbol(")"): 
                    balance -= 1
                    if balance == 0: 
                        break
                elif self.tokens[j] == Symbol(":") and balance == 1:
                    colon_idx = j
                j += 1
            
            if balance == 0 and colon_idx != -1:
                if j+1 < len(self.tokens) and self.tokens[j+1] == Symbol("["):
                    k = j + 2
                    while k < len(self.tokens) and self.tokens[k] != Symbol("]"):
                        k += 1
                    if k+1 < len(self.tokens) and self.tokens[k+1] == Symbol(":"):
                        if k+2 < len(self.tokens) and self.tokens[k+2] == Symbol("{"):
                            is_loop = True
                            j_end_paren = j
                            k_end_bracket = k
            
            if is_loop:
                start_toks = self.tokens[self.i+1 : colon_idx]
                end_toks = self.tokens[colon_idx+1 : j_end_paren]
                idx_name = self.tokens[j_end_paren+2].value if isinstance(self.tokens[j_end_paren+2], Identifier) else "_"
                
                loop_node = ASTNode(NodeType.Loop, identifier=f"loop_{self.i}")
                loop_node.args = [idx_name]
                self.current_node.children.append(loop_node)
                
                # Inject Start, End, then Body
                loop_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(start_toks)))
                loop_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(end_toks)))
                
                block_node = ASTNode(NodeType.Block)
                loop_node.children.append(block_node)
                self.stack.append(block_node)
                
                self.i = k_end_bracket + 3 # Skip `] : {`
                return
            
            self.parse_default(token)
        elif token.value == ";":
            self.i += 1
        else:
            self.parse_default(token)

    def parse_store(self):
        j = self.i + 1
        balance = 1
        while j < len(self.tokens) and balance > 0:
            if self.tokens[j] == Symbol("["): 
                balance += 1
            elif self.tokens[j] == Symbol("]"): 
                balance -= 1
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

    def parse_array_store(self, name: str, closing_bracket_idx: int):
        store_node = ASTNode(NodeType.Store)
        self.current_node.children.append(store_node)
        
        # Build ptr access AST expression: array_addr + index
        idx_tokens = self.tokens[self.i+2 : closing_bracket_idx]
        ptr_toks = [Identifier(name), Symbol("+"), Symbol("(")] + idx_tokens + [Symbol(")")]
        store_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(ptr_toks)))
        
        k = closing_bracket_idx + 2 # skip `] =`
        val_tokens = []
        while k < len(self.tokens) and self.tokens[k] != Symbol(";"):
            val_tokens.append(self.tokens[k])
            k += 1
        
        store_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(val_tokens)))
        self.i = k

    def parse_assignment(self, name: str):
        self.i += 2 
        
        # Context Mapping: name = (args) : { ...
        is_pipeline = False
        if self.i < len(self.tokens) and self.tokens[self.i] == Symbol("("):
            j = self.i
            balance = 0
            while j < len(self.tokens):
                if self.tokens[j] == Symbol("("): 
                    balance += 1
                elif self.tokens[j] == Symbol(")"): 
                    balance -= 1
                    if balance == 0: 
                        break
                j += 1
            # BUGFIX: Evaluates `j+1` (which is `:`) instead of `j` (which is `)`)
            if j+1 < len(self.tokens) and self.tokens[j+1] == Symbol(":"):
                if j+2 < len(self.tokens) and self.tokens[j+2] == Symbol("{"):
                    is_pipeline = True
                    
        if is_pipeline:
            assign_node = ASTNode(NodeType.Assignment, identifier=name)
            self.current_node.children.append(assign_node)
            
            self.i += 1 # Skip `(`
            args = []
            arg_constraints =[]
            is_type = False
            
            while self.i < len(self.tokens) and self.tokens[self.i] != Symbol(")"):
                if isinstance(self.tokens[self.i], Identifier):
                    args.append(self.tokens[self.i].value)
                    
                    # Peek ahead for constraint: e.g., `bytes[:4]` or `self[int]`
                    if self.i + 1 < len(self.tokens) and self.tokens[self.i+1] == Symbol("["):
                        self.i += 2 # Skip ident and `[`
                        constraint_toks = []
                        
                        # If the constraint starts with ':', it's a Space Slice! This is a Type!
                        if self.i < len(self.tokens) and self.tokens[self.i] == Symbol(":"):
                            is_type = True 
                            
                        while self.i < len(self.tokens) and self.tokens[self.i] != Symbol("]"):
                            constraint_toks.append(self.tokens[self.i])
                            self.i += 1
                        arg_constraints.append(constraint_toks)
                    else:
                        arg_constraints.append([])
                self.i += 1
                
            self.i += 1 # Skip `)`
            self.i += 2 # Skip `:` and `{`
            
            block_node = ASTNode(NodeType.Block)
            block_node.args = args
            block_node.arg_constraints = arg_constraints
            block_node.is_type = is_type
            
            assign_node.children.append(block_node)
            self.stack.append(block_node)
            return
            
        # Standard Primitive / Value Assignment
        assign_node = ASTNode(NodeType.Assignment, identifier=name)
        self.current_node.children.append(assign_node)
        
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
                if self.tokens[j] == Symbol("["): 
                    balance += 1
                elif self.tokens[j] == Symbol("]"): 
                    balance -= 1
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