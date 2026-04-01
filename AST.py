from dataclasses import dataclass, field
from enum import Enum, auto
import tokens
from tokens import Token, Symbol, Keyword, Identifier
from typing import List, Dict, Optional
import expression
from expression import ExprNode

class NodeType(Enum):
    Program     = auto()    
    Block       = auto()    # { ... } (Used for structs, funcs, and scopes)
    Assignment  = auto()    # x = ...
    FieldDecl   = auto()    # x : ... (Inside blocks)
    Return      = auto()    # return ...
    Expression  = auto()    # Wrapper for ExprNode
    Store       = auto()    # Wrapper for ExprNode
    Loop        = auto()    #[100] : i { ... }
    LoopControl = auto()    # label_asdf : next/end/expr

@dataclass
class ASTNode:
    node_type: NodeType
    # Logic / Structure
    children: List['ASTNode'] = field(default_factory=list)
    
    # Data for Blocks (Macro/Struct/Func)
    args: List[str] = field(default_factory=list) # e.g. (val) in thing = (val){...}
    
    # Identifiers / Values
    identifier: Optional[str] = None
    expr: Optional[ExprNode] = None  # If this node wraps an expression

def parse(tokens_in: List[Token]) -> ASTNode:
    root = ASTNode(NodeType.Program)
    # Stack stores tuples: (Node, is_expecting_closure_symbol)
    stack = [root] 
    
    i = 0
    while i < len(tokens_in):
        token = tokens_in[i]
        current_node = stack[-1]

        match token:
            case tokens.Symbol("["):
                # This logic is almost identical to Expr parsing, but we look for '=' after the ']'
                # Quick hack: scan ahead to find ']'
                j = i + 1
                balance = 1
                while j < len(tokens_in) and balance > 0:
                    if tokens_in[j] == Symbol("["): balance += 1
                    elif tokens_in[j] == Symbol("]"): balance -= 1
                    j += 1
                
                # Now tokens_in[j-1] is ']'. Check if next is '='
                if j < len(tokens_in) and tokens_in[j] == Symbol("="):
                    # Found: [ ... ] = ...
                    ptr_tokens = tokens_in[i+1 : j-1] # Inside brackets
                    
                    store_node = ASTNode(NodeType.Store)
                    current_node.children.append(store_node)
                    
                    # Parse Address
                    store_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(ptr_tokens)))
                    
                    # Parse Value (RHS)
                    # Skip [ ... ] = 
                    k = j + 1
                    val_tokens = []
                    while k < len(tokens_in) and tokens_in[k] != Symbol(";"):
                        val_tokens.append(tokens_in[k])
                        k += 1
                    
                    store_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(val_tokens)))
                    
                    i = k # Advance main loop
                    continue
                
            # --- 1. Variable Assignment / Definition: x = ... ---
            case tokens.Identifier(name):
                # Peek ahead: Is it assignment 'x =' or 'x :'?
                if i + 1 < len(tokens_in):
                    next_tok = tokens_in[i+1]
                    
                    # A. Assignment: x = ...
                    if next_tok == Symbol("="):
                        # This could be x = 1 (Expression)
                        # OR x = { ... } (Block/Struct literal)
                        # OR x = (arg) { ... } (Function/Macro)
                        
                        assign_node = ASTNode(NodeType.Assignment, identifier=name)
                        current_node.children.append(assign_node)
                        
                        i += 2 # Skip 'x' and '='
                        
                        if i < len(tokens_in) and tokens_in[i] == Symbol("["):
                            j = i + 1
                            balance = 1
                            while j < len(tokens_in) and balance > 0:
                                if tokens_in[j] == Symbol("["): 
                                    balance += 1
                                elif tokens_in[j] == Symbol("]"): 
                                    balance -= 1
                                j += 1
                                
                            if j < len(tokens_in) and tokens_in[j] == Symbol(":"):
                                loop_node = ASTNode(NodeType.Loop)
                                assign_node.children.append(loop_node)
                                
                                # 1. Parse loop count expr
                                count_toks = tokens_in[i+1 : j-1]
                                loop_node.children.append(ASTNode(NodeType.Expression, expr=expression.parse_expression(count_toks)))
                                
                                # 2. Grab loop variable (i)
                                loop_node.identifier = tokens_in[j+1].value
                                
                                # 3. Create the Body Block
                                block_node = ASTNode(NodeType.Block)
                                loop_node.children.append(block_node)
                                stack.append(block_node)
                                
                                i = j + 3 # Skip ':', 'i', and '{'
                                continue

                        # Check for Arguments definition: x = (a,b) { ... }
                        args = []
                        if i < len(tokens_in) and tokens_in[i] == Symbol("("):
                            # Parse args list
                            i += 1
                            while i < len(tokens_in) and tokens_in[i] != Symbol(")"):
                                if isinstance(tokens_in[i], tokens.Identifier):
                                    args.append(tokens_in[i].value)
                                i += 1
                            i += 1 # Skip ')'
                        
                        # Check for Block Start: {
                        if i < len(tokens_in) and tokens_in[i] == Symbol("{"):
                            block_node = ASTNode(NodeType.Block)
                            block_node.args = args # Attach args to the block
                            assign_node.children.append(block_node)
                            stack.append(block_node)
                            # i is currently '{', loop continues to next token
                            
                            i += 1 
                        else:
                            # It's a standard expression: x = 5 + y;
                            # Collect tokens until ';' or newline
                            expr_tokens = []
                            while i < len(tokens_in) and tokens_in[i] != Symbol(";"):
                                expr_tokens.append(tokens_in[i])
                                i += 1
                            
                            expr_tree = expression.parse_expression(expr_tokens)
                            assign_node.children.append(ASTNode(NodeType.Expression, expr=expr_tree))
                        
                        continue # Loop handled i increment

                    # B. Field Declaration (inside Block): x : 1
                    # Loop Control (label : next / label : expr) 
                    elif next_tok == Symbol(":"):
                        k = i + 2
                        is_control = False
                        while k < len(tokens_in) and tokens_in[k] not in (Symbol(";"), Symbol(","), Symbol("}")):
                            k += 1
                        if k < len(tokens_in) and tokens_in[k] == Symbol(";"):
                            is_control = True

                        if current_node.node_type == NodeType.Block and not is_control:
                            
                            field_node = ASTNode(NodeType.FieldDecl, identifier=name)
                            current_node.children.append(field_node)

                            i += 2 # Skip 'x' and ':'

                            # Parse Value (Expression)
                            expr_tokens = []
                            # Read until ',' or '}' (end of field)
                            while i < len(tokens_in) and tokens_in[i] not in (Symbol(","), Symbol("}")):
                                expr_tokens.append(tokens_in[i])
                                i += 1

                            expr_tree = expression.parse_expression(expr_tokens)
                            field_node.children.append(ASTNode(NodeType.Expression, expr=expr_tree))

                            # If we hit a comma, skip it
                            if i < len(tokens_in) and tokens_in[i] == Symbol(","):
                                i += 1
                            continue
                        else:
                            control_node = ASTNode(NodeType.LoopControl, identifier=name)
                            current_node.children.append(control_node)
                            i += 2 # Skip label and ':'
                            
                            tok_val = getattr(tokens_in[i], "value", "")
                            if tok_val == "next" or tok_val == "end":
                                control_node.args = [tok_val]
                                i += 1 # Skip 'next'/'end'
                            else:
                                control_node.args = ["expr"]
                                expr_tokens = []
                                while i < len(tokens_in) and tokens_in[i] != Symbol(";"):
                                    expr_tokens.append(tokens_in[i])
                                    i += 1
                                expr_tree = expression.parse_expression(expr_tokens)
                                control_node.children.append(ASTNode(NodeType.Expression, expr=expr_tree))
                            continue

                # If not assignment, it's likely an expression start (Function call or Math)
                # Fallthrough to Expression handling below

            # --- 2. Block Start (Anonymous) ---
            case tokens.Symbol("{"):
                block_node = ASTNode(NodeType.Block)
                current_node.children.append(block_node)
                stack.append(block_node)

            # --- 3. Block End ---
            case tokens.Symbol("}"):
                if len(stack) > 1:
                    stack.pop()
                else:
                    raise SyntaxError("Unexpected '}' - Stack underflow")

            # --- 4. Return ---
            case tokens.Keyword("return"):
                ret_node = ASTNode(NodeType.Return)
                current_node.children.append(ret_node)
                i += 1
                
                # Parse return value
                expr_tokens = []
                while i < len(tokens_in) and tokens_in[i] not in (Symbol(";"), Symbol("}")):
                    expr_tokens.append(tokens_in[i])
                    i += 1
                
                if expr_tokens:
                    expr_tree = expression.parse_expression(expr_tokens)
                    ret_node.children.append(ASTNode(NodeType.Expression, expr=expr_tree))
                
                continue

            # --- 5. Generic Expression (Statement) ---
            case _:
                if token == Symbol(";"): 
                    pass # Skip empty statements
                else:
                    # Treat line as expression statement (e.g., function call "do_thing(1)")
                    expr_tokens = []
                    while i < len(tokens_in) and tokens_in[i] != Symbol(";"):
                        # Stop if we hit a closing brace that belongs to parent
                        if tokens_in[i] == Symbol("}"): 
                            i -= 1 # Back up so the main loop handles '}'
                            break
                        expr_tokens.append(tokens_in[i])
                        i += 1
                    
                    if expr_tokens:
                        expr_tree = expression.parse_expression(expr_tokens)
                        current_node.children.append(ASTNode(NodeType.Expression, expr=expr_tree))

        i += 1
    
    return root