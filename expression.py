from dataclasses import dataclass, field
from enum import Enum, auto
import tokens
from tokens import Token, Symbol, Keyword, Identifier, Value
from typing import List, Optional

class ExprNodeType(Enum):
    BinaryOp       = auto()    
    Value          = auto()    
    Identifier     = auto()    
    Call           = auto()    
    ArrayAlloc     = auto()    
    BlockLiteral   = auto()    
    Deref          = auto()

@dataclass
class ExprNode:
    type: ExprNodeType
    value: Token = None
    left: Token = None
    right: Token = None
    children: List['ExprNode | Token'] = field(default_factory=list)

def get_precedence(op: Token) -> int:
    if op in tokens.weight_dict:
        return tokens.weight_dict[op]
    return 4


class ExpressionParser:
    def __init__(self, token_list: List[Token]):
        self.tokens = token_list
        self.i = 0
        self.output_queue =[]
        self.operator_stack = []

    def parse(self) -> Optional[ExprNode]:
        while self.i < len(self.tokens):
            token = self.tokens[self.i]
            
            # Dynamic Dispatch just like compiler.py
            method_name = f"parse_{type(token).__name__}"
            visitor = getattr(self, method_name, self.parse_default)
            visitor(token)
            
            self.i += 1
            
        # Flush the remaining operators
        while self.operator_stack:
            op = self.operator_stack.pop()
            if len(self.output_queue) < 2:
                raise SyntaxError(f"Invalid Expression: Not enough operands for '{op.value}'")
            right = self.output_queue.pop()
            left = self.output_queue.pop()
            self.output_queue.append(ExprNode(ExprNodeType.BinaryOp, value=op, left=left, right=right))

        if not self.output_queue:
            return None
        return self.output_queue[0]

    def parse_Value(self, token: Value):
        self.output_queue.append(ExprNode(ExprNodeType.Value, value=token))

    def parse_Identifier(self, token: Identifier):
        # Look ahead for Function Call: ident(...)
        if self.i + 1 < len(self.tokens) and self.tokens[self.i+1] == Symbol("("):
            func_name = token
            self.i += 2 # Skip ident and (
            args =[]
            current_arg_tokens =[]
            balance = 1
            
            while self.i < len(self.tokens):
                cur_token = self.tokens[self.i]
                if cur_token == Symbol(")"):
                    balance -= 1
                    if balance == 0: 
                        break
                elif cur_token == Symbol("("):
                    balance += 1
                elif cur_token == Symbol(",") and balance == 1:
                    if current_arg_tokens:
                        args.append(parse_expression(current_arg_tokens))
                        current_arg_tokens =[]
                    self.i += 1
                    continue
                
                current_arg_tokens.append(cur_token)
                self.i += 1
            
            if current_arg_tokens:
                args.append(parse_expression(current_arg_tokens))
            
            self.output_queue.append(ExprNode(ExprNodeType.Call, value=func_name, children=args))
        else:
            self.output_queue.append(ExprNode(ExprNodeType.Identifier, value=token))

    def parse_Symbol(self, token: Symbol):
        # Sub-dispatch specific symbols to clean methods
        symbol_map = {
            "[": self.Symbol_LBracket,
            "(": self.Symbol_LParen,
            ")": self.Symbol_RParen,
        }
        handler = symbol_map.get(token.value, self.Symbol_Operator)
        handler(token)

    def Symbol_LBracket(self, token: Symbol):
        # Handle Array Alloc [:10]
        if self.i + 1 < len(self.tokens) and self.tokens[self.i+1] == Symbol(":"):
            if self.i + 2 < len(self.tokens) and isinstance(self.tokens[self.i+2], Value):
                size_token = self.tokens[self.i+2]
                node = ExprNode(ExprNodeType.ArrayAlloc, value=size_token)
                self.output_queue.append(node)
                self.i += 3 # Skip[ : 10
                
                if self.i >= len(self.tokens) or self.tokens[self.i] != Symbol("]"):
                    raise SyntaxError("Missing ] for array alloc")
            else:
                raise SyntaxError("Invalid array alloc syntax")
        else:
            # Handle Deref [ptr]
            inner_tokens =[]
            bracket_balance = 1
            self.i += 1 
            while self.i < len(self.tokens):
                cur_token = self.tokens[self.i]
                if cur_token == Symbol("["): 
                    bracket_balance += 1
                elif cur_token == Symbol("]"): 
                    bracket_balance -= 1
                
                if bracket_balance == 0:
                    break
                inner_tokens.append(cur_token)
                self.i += 1
            
            if not inner_tokens:
                raise SyntaxError("Empty[] dereference")
                
            inner_expr = parse_expression(inner_tokens)
            node = ExprNode(ExprNodeType.Deref, left=inner_expr)
            self.output_queue.append(node)

    def Symbol_LParen(self, token: Symbol):
        self.operator_stack.append(token)

    def Symbol_RParen(self, token: Symbol):
        while self.operator_stack and self.operator_stack[-1] != Symbol("("):
            top_op = self.operator_stack.pop()
            
            # 3. Add safety check here too
            if len(self.output_queue) < 2:
                raise SyntaxError(f"Invalid Expression: Not enough operands for '{top_op.value}'")
                
            right = self.output_queue.pop()
            left = self.output_queue.pop()
            self.output_queue.append(ExprNode(ExprNodeType.BinaryOp, value=top_op, left=left, right=right))
            
        if self.operator_stack:
            self.operator_stack.pop() # Pop '('

    def Symbol_Operator(self, token: Symbol):
        if token not in tokens.weight_dict:
            return 
            
        prec = get_precedence(token)
        while (self.operator_stack and 
               isinstance(self.operator_stack[-1], Symbol) and 
               self.operator_stack[-1] != Symbol("(") and
               get_precedence(self.operator_stack[-1]) >= prec):
            
            top_op = self.operator_stack.pop()
            
            # 2. Add safety check instead of throwing an IndexError
            if len(self.output_queue) < 2:
                raise SyntaxError(f"Invalid Expression: Not enough operands for '{top_op.value}'")
                
            right = self.output_queue.pop()
            left = self.output_queue.pop()
            self.output_queue.append(ExprNode(ExprNodeType.BinaryOp, value=top_op, left=left, right=right))
            
        self.operator_stack.append(token)


    def parse_default(self, token: Token):
        raise NotImplementedError(f"No expression for {token}")


# Maintain the old entrypoint so `AST.py` doesn't need changing
def parse_expression(token_list: List[Token]) -> Optional[ExprNode]:
    parser = ExpressionParser(token_list)
    return parser.parse()