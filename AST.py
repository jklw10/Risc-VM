from dataclasses import dataclass, field
from enum import Enum, auto
from tokens import Token, Symbol, Keyword, Identifier
from typing import List, Dict, Optional, Any
import expression
from expression import ExprNode

class NodeType(Enum):
    Program       = auto()    
    Block         = auto()    
    Assignment    = auto()    
    Pipeline      = auto()    
    Binding       = auto()    
    FieldDecl     = auto()    
    Return        = auto()    
    Expression    = auto()    
    Store         = auto()    
    LoopControl   = auto()    
    StoreOrAssign = auto()    

@dataclass
class ASTNode:
    node_type: NodeType
    children: List['ASTNode'] = field(default_factory=list)
    args: List[str] = field(default_factory=list)
    identifier: Optional[str] = None
    expr: Optional[ExprNode] = None   
    is_type: bool = False           
    type_name: str = ""
    outputs: List[Dict[str, str]] = field(default_factory=list)

class ASTParser:
    def __init__(self, tokens_in: List[Token]):
        self.tokens = tokens_in
        self.i = 0
        self.root = ASTNode(NodeType.Program)
        self.stack = [self.root]

    @property
    def current_node(self):
        return self.stack[-1]

    def _get_context(self, offset=0):
        idx = min(max(0, self.i + offset), len(self.tokens) - 1)
        if not self.tokens: 
            return "Empty file"
        start = max(0, idx - 10)
        end = min(len(self.tokens), idx + 10)
        
        out =[]
        for j in range(start, end):
            val = str(getattr(self.tokens[j], 'value', type(self.tokens[j]).__name__))
            if j == idx:
                out.append(f"\n   >>> {val} <<<   \n")
            else:
                out.append(val)
        return " ".join(out)

    def parse(self) -> ASTNode:
        try:
            while self.i < len(self.tokens):
                token = self.tokens[self.i]
                method_name = f"parse_{type(token).__name__}"
                visitor = getattr(self, method_name, self.parse_default)
                visitor(token)
                
        except Exception as e:
            raise SyntaxError(f"{str(e)}\n\nError near tokens:\n{self._get_context()}") from None
            
        if len(self.stack) > 1:
            raise SyntaxError(f"Missing '}}' (Stack has {len(self.stack) - 1} unclosed blocks)\nNear end of file:\n{self._get_context(-1)}")
            
        return self.root

    def parse_Keyword(self, token: Keyword):
        raise SyntaxError("Keywords are reserved but unimplemented")

    def parse_Identifier(self, token: Identifier, initial_name: Optional[str] = None):
        start_i = self.i
        name = initial_name if initial_name is not None else token.value
        if initial_name is None:
            self.i += 1
        
        # Desugar .@op(+) instantly
        while self.i < len(self.tokens) and self.tokens[self.i] == Symbol("."):
            if self.i + 1 < len(self.tokens) and self.tokens[self.i+1] == Symbol("@"):
                if (self.i + 5 < len(self.tokens) and 
                    isinstance(self.tokens[self.i+2], Identifier) and self.tokens[self.i+2].value == "op" and
                    self.tokens[self.i+3] == Symbol("(") and
                    self.tokens[self.i+5] == Symbol(")")):
                    
                    op_sym = self.tokens[self.i+4].value
                    name += f".__op_{op_sym}"
                    self.i += 6
                    continue
            if self.i + 1 < len(self.tokens) and isinstance(self.tokens[self.i+1], Identifier):
                name += "." + self.tokens[self.i+1].value
                self.i += 2
            else:
                break
                
        type_name = ""
        is_array_store = False
        closing_bracket_idx = -1
        
        # Check for[type] context mapping
        if self.i < len(self.tokens) and self.tokens[self.i] == Symbol("["):
            j = self.i + 1
            balance = 1
            while j < len(self.tokens) and balance > 0:
                if self.tokens[j] == Symbol("["): balance += 1
                elif self.tokens[j] == Symbol("]"): balance -= 1
                j += 1
            closing_bracket_idx = j - 1
            
            # Lookahead to resolve if LHS of statement
            k = j
            is_lhs = False
            while k < len(self.tokens):
                if self.tokens[k] == Symbol("="):
                    is_lhs = True
                    break
                if self.tokens[k] == Symbol(":"):
                    temp_k = k + 1
                    while temp_k < len(self.tokens) and self.tokens[temp_k] not in (Symbol(";"), Symbol("{")):
                        if self.tokens[temp_k] == Symbol("="):
                            is_lhs = True
                            break
                        temp_k += 1
                    break
                if self.tokens[k] == Symbol(";"):
                    break
                k += 1
                
            if is_lhs:
                inner_tokens = self.tokens[self.i+1 : closing_bracket_idx]
                if len(inner_tokens) == 1 and isinstance(inner_tokens[0], Identifier):
                    type_name = inner_tokens[0].value
                    self.i = closing_bracket_idx + 1
                else:
                    is_array_store = True

        if is_array_store:
            self.parse_array_store(name, closing_bracket_idx)
            return

        outputs =[]
        # Check for Dataflow Outputs `: result[int]` or `: (out1, out2)`
        if self.i < len(self.tokens) and self.tokens[self.i] == Symbol(":"):
            k = self.i + 1
            has_eq = False
            while k < len(self.tokens) and self.tokens[k] not in (Symbol(";"), Symbol("{")):
                if self.tokens[k] == Symbol("="):
                    has_eq = True
                    break
                k += 1
                
            if has_eq:
                self.i += 1 
                if self.tokens[self.i] == Symbol("("):
                    self.i += 1
                    while self.i < len(self.tokens) and self.tokens[self.i] != Symbol(")"):
                        if self.tokens[self.i] == Symbol(","):
                            self.i += 1
                            continue
                        if isinstance(self.tokens[self.i], Identifier):
                            out_name = self.tokens[self.i].value
                            out_type = ""
                            self.i += 1
                            if self.i < len(self.tokens) and self.tokens[self.i] == Symbol("["):
                                self.i += 1
                                if isinstance(self.tokens[self.i], Identifier):
                                    out_type = self.tokens[self.i].value
                                    self.i += 1
                                if self.tokens[self.i] == Symbol("]"):
                                    self.i += 1
                            outputs.append({"name": out_name, "type": out_type})
                        else:
                            self.i += 1 
                    if self.i < len(self.tokens) and self.tokens[self.i] == Symbol(")"):
                        self.i += 1
                else:
                    if isinstance(self.tokens[self.i], Identifier):
                        out_name = self.tokens[self.i].value
                        out_type = ""
                        self.i += 1
                        if self.i < len(self.tokens) and self.tokens[self.i] == Symbol("["):
                            self.i += 1
                            if isinstance(self.tokens[self.i], Identifier):
                                out_type = self.tokens[self.i].value
                                self.i += 1
                            if self.tokens[self.i] == Symbol("]"):
                                self.i += 1
                        outputs.append({"name": out_name, "type": out_type})

        # Check for '=' Assignment / Pipeline Fulcrum
        if self.i < len(self.tokens) and self.tokens[self.i] == Symbol("="):
            self.i += 1
            
            if self._peek_is_pipeline():
                pipe_node = self._parse_pipeline_tail(identifier=name)
                pipe_node.type_name = type_name
                pipe_node.outputs = outputs
                return
            elif self.i < len(self.tokens) and self.tokens[self.i] == Symbol("{"):
                # Syntactic sugar for pure namespaces: `name = { ... }`
                pipe_node = ASTNode(NodeType.Pipeline, identifier=name)
                self.current_node.children.append(pipe_node)
                
                bindings_block = ASTNode(NodeType.Block)
                pipe_node.children.append(bindings_block)
                
                # Emulate a 0-byte type definition
                dummy_binding = ASTNode(NodeType.Binding, identifier="namespace", is_type=True)
                import tokens
                dummy_binding.expr = expression.ExprNode(
                    expression.ExprNodeType.Value,
                    value=tokens.Value(0)
                )
                bindings_block.children.append(dummy_binding)
                
                self.i += 1 # skip '{'
                
                body_node = ASTNode(NodeType.Block)
                pipe_node.children.append(body_node)
                self.stack.append(body_node)
                return
            else:
                node = ASTNode(NodeType.StoreOrAssign, identifier=name, type_name=type_name)
                self.current_node.children.append(node)
                expr_tokens = []
                while self.i < len(self.tokens) and self.tokens[self.i] != Symbol(";"):
                    if self.tokens[self.i] == Symbol("}"):
                        break
                    expr_tokens.append(self.tokens[self.i])
                    self.i += 1
                if expr_tokens:
                    expr_tree = expression.parse_expression(expr_tokens)
                    node.children.append(ASTNode(NodeType.Expression, expr=expr_tree))
                return
                
        self.i = start_i
        self.parse_default(token)

    def _peek_is_pipeline(self) -> bool:
        if self.i >= len(self.tokens) or self.tokens[self.i] != Symbol("("):
            return False
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
            
        if j < len(self.tokens) and self.tokens[j] == Symbol(")"):
            j += 1
            # Optional colon
            if j < len(self.tokens) and self.tokens[j] == Symbol(":"):
                j += 1
            if j < len(self.tokens) and self.tokens[j] == Symbol("{"):
                return True
        return False

    def _parse_pipeline_tail(self, identifier: Optional[str]) -> ASTNode:
        pipeline_node = ASTNode(NodeType.Pipeline, identifier=identifier)
        self.current_node.children.append(pipeline_node)
        self.i += 1 
        
        bindings_block = ASTNode(NodeType.Block)
        pipeline_node.children.append(bindings_block)
        
        while self.i < len(self.tokens) and self.tokens[self.i] != Symbol(")"):
            bind_toks =[]
            while self.i < len(self.tokens) and self.tokens[self.i] not in (Symbol(","), Symbol(")")):
                bind_toks.append(self.tokens[self.i])
                self.i += 1
                
            if bind_toks:
                is_assign = False
                for idx, t in enumerate(bind_toks):
                    if t == Symbol("="):
                        name_toks = bind_toks[:idx]
                        expr_toks = bind_toks[idx+1:]
                        bindings_block.children.append(self.parse_binding(name_toks, expr_toks))
                        is_assign = True
                        break
                if not is_assign:
                    bindings_block.children.append(self.parse_binding(bind_toks, []))
                    
            if self.tokens[self.i] == Symbol(","):
                self.i += 1
            
        if self.i < len(self.tokens) and self.tokens[self.i] == Symbol(")"):
            self.i += 1
            
        if self.i < len(self.tokens) and self.tokens[self.i] == Symbol(":"):
            self.i += 1
            
        self.i = self.seek_and_skip(self.i, Symbol("{"))

        body_node = ASTNode(NodeType.Block)
        pipeline_node.children.append(body_node)
        self.stack.append(body_node)
        
        return pipeline_node

    def parse_binding(self, name_toks, expr_toks) -> ASTNode:
        node = ASTNode(NodeType.Binding)
        
        is_array_type_decl = (len(name_toks) >= 4 and isinstance(name_toks[0], Identifier) and name_toks[1] == Symbol("["))
        
        if is_array_type_decl:
            node.identifier = name_toks[0].value
            if name_toks[2] == Symbol(":"): 
                node.is_type = True
                node.expr = expression.parse_expression(name_toks[3:-1])
            else: 
                if isinstance(name_toks[2], Identifier):
                    node.type_name = name_toks[2].value
        elif len(name_toks) >= 1 and isinstance(name_toks[0], Identifier):
            node.identifier = name_toks[0].value
            # If the parameter has trailing tokens (e.g. `x == 1`), it's a Pattern Match Constraint!
            if len(name_toks) > 1:
                node.expr = expression.parse_expression(name_toks)
                
        if expr_toks:
            node.expr = expression.parse_expression(expr_toks)
            
        return node

    def parse_Symbol(self, token: Symbol):
        if token.value == "[":
            self.parse_store()  
        elif token.value == ".":
            # Context-prefixed declarations like `.func = ...` or `.@op(+) = ...`
            if self.i + 1 < len(self.tokens) and (isinstance(self.tokens[self.i+1], Identifier) or self.tokens[self.i+1] == Symbol("@")):
                self.parse_Identifier(Identifier(""), initial_name="")
                return
            self.parse_default(token)
        elif token.value == "{":
            block_node = ASTNode(NodeType.Block)
            self.current_node.children.append(block_node)
            self.stack.append(block_node)
            self.i += 1
        elif token.value == "}":
            if len(self.stack) > 1:
                popped_node = self.stack.pop()
            else:
                raise SyntaxError(f"Unexpected '}}' - Stack underflow\nError near tokens:\n{self._get_context()}")
            self.i += 1
        elif token.value == "(":
            if self._peek_is_pipeline():
                loop_name = f"loop_{self.i}"
                self._parse_pipeline_tail(identifier=loop_name)
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
            
        closing_bracket_idx = j - 1
            
        while j < len(self.tokens) and self.tokens[j] != Symbol("="):
            if self.tokens[j] == Symbol(";"): 
                break
            j += 1
            
        if j < len(self.tokens) and self.tokens[j] == Symbol("="):
            ptr_tokens = self.tokens[self.i+1 : closing_bracket_idx]
                
            store_node = ASTNode(NodeType.Store)
            self.current_node.children.append(store_node)
            store_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(ptr_tokens)))
            
            k = j + 1
            val_tokens =[]
            while k < len(self.tokens) and self.tokens[k] != Symbol(";"):
                if self.tokens[k] == Symbol("}"):
                    break
                val_tokens.append(self.tokens[k])
                k += 1
                
            store_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(val_tokens)))
            self.i = k
        else:
            self.parse_default(self.tokens[self.i])

    def parse_array_store(self, name: str, closing_bracket_idx: int):
        store_node = ASTNode(NodeType.Store)
        self.current_node.children.append(store_node)
        idx_tokens = self.tokens[self.i+1 : closing_bracket_idx]
        ptr_toks =[Identifier(name), Symbol("+"), Symbol("(")] + idx_tokens + [Symbol(")")]
        store_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(ptr_toks)))
        
        k = closing_bracket_idx + 1
        k = self.seek_and_skip(k, Symbol("="))
            
        val_tokens =[]
        while k < len(self.tokens) and self.tokens[k] != Symbol(";"):
            if self.tokens[k] == Symbol("}"):
                break
            val_tokens.append(self.tokens[k])
            k += 1
        
        store_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(val_tokens)))
        self.i = k

    def seek_and_skip(self, k, symbol):
        while k < len(self.tokens) and self.tokens[k] != symbol:
            k += 1
        if k < len(self.tokens) and self.tokens[k] == symbol:
            k += 1
        return k

    def parse_default(self, token: Token):
        if token == Symbol(";"):
            self.i += 1
            return
            
        expr_tokens =[]
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