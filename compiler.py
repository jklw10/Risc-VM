import macros
from macros import asm
from AST import NodeType, ASTNode
from expression import ExprNodeType, ExprNode
from typing import Dict, Optional, List
from dataclasses import dataclass
from tokens import Symbol
from tokens import Identifier, Value
import tokens
import AST
import expression
@dataclass
class SymbolInfo:
    offset_from_base: int  
    is_function: bool = False
    arg_count: int = 0
    is_loop: bool = False
    label: str = ""
    l_start: str = ""
    l_next: str = ""
    l_end: str = ""
    var_offset: int = 0
    type_name: str = "" 

class Compiler:
    def __init__(self):
        self.scopes: List[Dict[str, SymbolInfo]] = [{}]
        self.types = {} # <-- Store comptime types here!
        self.current_stack_depth = 0
        self.label_counter = 0

    def get_symbol(self, name: str) -> Optional[SymbolInfo]:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def declare_symbol(self, name: str, is_fn=False, args=0, type_name=""):
        info = SymbolInfo(offset_from_base=self.current_stack_depth-4,
                           is_function=is_fn, arg_count=args, type_name=type_name)
        self.scopes[-1][name] = info
        return info

    def enter_scope(self):
        self.scopes.append({})

    def exit_scope(self):
        self.scopes.pop()

    def get_unique_label(self, prefix="lbl"):
        self.label_counter += 1
        return f"{prefix}_{self.label_counter}"

    def compile(self, node: ASTNode):
        macros.init()
        self._compile_node(node)
        return asm

    def _compile_node(self, node: ASTNode):
        method_name = node.node_type.name
        visitor = getattr(self, method_name, self.error)
        return visitor(node)
        
    def error(self, node):
        raise NotImplementedError(f"No compile method for {node.node_type}")

    def Loop(self, node):
        label_name = node.identifier
        var_name = node.args[0]
        
        # node.children[1] = End limit expression
        self._compile_expr(node.children[1].expr)
        end_offset = self.current_stack_depth - 4
        
        # node.children[0] = Start limit expression (This becomes our iterator var)
        self._compile_expr(node.children[0].expr)
        
        self.enter_scope()
        var_info = self.declare_symbol(var_name)
        
        l_start = self.get_unique_label(f"{label_name}_start")
        l_next  = self.get_unique_label(f"{label_name}_next")
        l_end   = self.get_unique_label(f"{label_name}_end")
        
        loop_info = SymbolInfo(
            offset_from_base=0, 
            is_function=False, 
            arg_count=0,
            is_loop=True,
            label=label_name,
            l_start=l_start,
            l_next=l_next,
            l_end=l_end,
            var_offset=var_info.offset_from_base
        )
        self.scopes[-1][f"__loop_{label_name}"] = loop_info
        
        asm.label(l_start)
        asm.load(macros.t0, macros.stack_ptr, var_info.offset_from_base - self.current_stack_depth)
        asm.load(macros.t1, macros.stack_ptr, end_offset - self.current_stack_depth)
        asm.bge(macros.t0, macros.t1, l_end)
        
        self._compile_node(node.children[2])
        
        asm.label(l_next)
        asm.load(macros.t0, macros.stack_ptr, var_info.offset_from_base - self.current_stack_depth)
        asm.addi(macros.t0, macros.t0, 1)
        asm.store(macros.stack_ptr, var_info.offset_from_base - self.current_stack_depth, macros.t0)
        asm.jal(macros.x0, l_start)
        
        asm.label(l_end)
        self.exit_scope()
        
        macros.pop(macros.t0) # Pop iteration start var out of stack
        macros.pop(macros.t0) # Pop end var out of stack
        self.current_stack_depth -= 8

    def LoopControl(self, node):
        target_loop = None
        for scope in reversed(self.scopes):
            key = f"__loop_{node.identifier}"
            if key in scope:
                target_loop = scope[key]
                break
                
        if not target_loop: 
            raise ValueError(f"Loop label {node.identifier} not found!")

        target_depth = target_loop.var_offset + 4 
        diff = self.current_stack_depth - target_depth

        cmd = node.args[0]
        if cmd == "end":
            if diff > 0: asm.addi(macros.stack_ptr, macros.stack_ptr, -diff)
            asm.jal(macros.x0, target_loop.l_end)
        elif cmd == "next":
            if diff > 0: asm.addi(macros.stack_ptr, macros.stack_ptr, -diff)
            asm.jal(macros.x0, target_loop.l_next)
        elif cmd == "expr":
            self._compile_expr(node.children[0].expr)
            macros.pop(macros.t0)
            self.current_stack_depth -= 4
            
            if diff > 0: asm.addi(macros.stack_ptr, macros.stack_ptr, -diff)
            
            # Write new value cleanly back to index variable
            asm.store(macros.stack_ptr, -4, macros.t0)
            asm.jal(macros.x0, target_loop.l_start)

    def Return(self, node):
        if node.children:
            child = node.children[0]
            if child.node_type == NodeType.Expression:
                self._compile_expr(child.expr)
            else:
                self._compile_node(child)
                
            macros.pop(macros.t0) 
            self.current_stack_depth -= 4
            asm.addi(macros.a0, macros.t0, 0)
        else:
            asm.addi(macros.a0, macros.x0, 0)
            
        if self.current_stack_depth > 0:
            asm.addi(macros.stack_ptr, macros.stack_ptr, -self.current_stack_depth)

        asm.jalr(macros.x0, macros.ra, 0)

    def Expression(self, node):
        if node.expr:
            self._compile_expr(node.expr)
            # Prevent standalone statement expressions from leaking memory!
            macros.pop(macros.t0)
            self.current_stack_depth -= 4

    def FieldDecl(self, node):
        child = node.children[0]
        if child.node_type == NodeType.Expression:
            self._compile_expr(child.expr)
        else:
            self._compile_node(child)
        self.declare_symbol(node.identifier)

    def Block(self, node):
        self.enter_scope()
        start_depth = self.current_stack_depth
        
        for child in node.children:
            self._compile_node(child)
            
        # Crucial scope cleanup! Protects loops.
        diff = self.current_stack_depth - start_depth
        if diff > 0:
            asm.addi(macros.stack_ptr, macros.stack_ptr, -diff)
            self.current_stack_depth = start_depth
            
        self.exit_scope()
    
    def _handle_import(self, namespace: str, filepath: str):
        """Loads a .w file, namespaces its AST declarations, and compiles it in-place."""
        
        with open(filepath, 'r') as f:
            source = f.read()
            
        imported_tokens = tokens.tokenize(source)
        imported_ast = AST.parse(imported_tokens)
        
        # 1. Gather top-level elements
        top_level_names = set()
        for node in imported_ast.children:
            if getattr(node, 'identifier', None):
                top_level_names.add(node.identifier)
                
        # 2. Namespace renamer visitor
        def replace_names(node):
            if isinstance(node, AST.ASTNode):
                if getattr(node, 'identifier', None) in top_level_names:
                    node.identifier = f"{namespace}.{node.identifier}"
                    
                if hasattr(node, 'arg_constraints'):
                    for constraint_toks in node.arg_constraints:
                        for i, tok in enumerate(constraint_toks):
                            if isinstance(tok, tokens.Identifier) and tok.value in top_level_names:
                                constraint_toks[i] = tokens.Identifier(f"{namespace}.{tok.value}")
                                
                for child in node.children:
                    replace_names(child)
                if node.expr:
                    replace_names(node.expr)
                    
            elif isinstance(node, expression.ExprNode):
                if node.type in (expression.ExprNodeType.Identifier, expression.ExprNodeType.Call):
                    if isinstance(node.value, tokens.Identifier) and node.value.value in top_level_names:
                        node.value = tokens.Identifier(f"{namespace}.{node.value.value}")
                elif node.type == expression.ExprNodeType.Macro:
                    for i, child in enumerate(node.children):
                        if isinstance(child, tokens.Identifier) and child.value in top_level_names:
                            node.children[i] = tokens.Identifier(f"{namespace}.{child.value}")
                            
                for child in node.children:
                    if isinstance(child, (AST.ASTNode, expression.ExprNode)):
                        replace_names(child)
                if node.left: replace_names(node.left)
                if node.right: replace_names(node.right)

        replace_names(imported_ast)
        
        # 3. Compile the namespace'd AST natively into our context
        for child in imported_ast.children:
            self._compile_node(child)
    def Assignment(self, node):
        name = node.identifier
        if node.children and node.children[0].node_type == NodeType.Expression:
            expr_node = node.children[0].expr
            if expr_node and expr_node.type == ExprNodeType.Macro and expr_node.value.value == "import":
                # Stringify the path out of the raw token identifiers/symbols
                path = "".join(str(t.value) for t in expr_node.children)
                self._handle_import(name, path)
                return
        if node.children and node.children[0].node_type == NodeType.Block and node.children[0].args:
            block_node = node.children[0]
            
            if getattr(block_node, "is_type", False):
                comptime_size = 0
                for constraint in block_node.arg_constraints:
                    if constraint and constraint[0] == Symbol(":"):
                        expr_toks = constraint[1:]
                        import expression 
                        size_expr = expression.parse_expression(expr_toks)
                        comptime_size = self._evaluate_comptime(size_expr)
                        break
                        
                self.types[name] = {"size": comptime_size, "methods": {}}
                print(f"[Comptime] Registered Type: {name} (Size: {comptime_size} bytes)")
                
                # Scan the block for methods like `value.add = (self, other) : { ... }`
                for child in block_node.children:
                    if child.node_type == NodeType.Assignment and "." in child.identifier:
                        base, method_name = child.identifier.split(".", 1)
                        if child.children and child.children[0].node_type == NodeType.Block:
                            # Compile the method globally as a standard function!
                            global_func_name = f"__{name}_{method_name}"
                            self.types[name]["methods"][method_name] = global_func_name
                            self._compile_function_def(global_func_name, child.children[0])
                return 
                
            self._compile_function_def(name, block_node)
        else:
            child = node.children[0]
            assigned_type = ""
            if child.node_type == NodeType.Expression:
                assigned_type = self._compile_expr(child.expr) or "" # Catch the type returned!
            else:
                self._compile_node(child)
                
            self.declare_symbol(name, type_name=assigned_type)

    def Store(self, node):
        self._compile_expr(node.children[1].expr)
        self._compile_expr(node.children[0].expr)
        macros.pop_mem()
        self.current_stack_depth -= 8

    def Deref(self, node):
        self._compile_expr(node.left)
        macros.pop(macros.t0) 
        asm.load(macros.t1, macros.t0, 0)
        macros.push(macros.t1)

    def Program(self, node):
        for child in node.children:
            self._compile_node(child)

    def _compile_function_def(self, name: str, block_node: ASTNode):
        end_label = self.get_unique_label("end_func")
        asm.jal(macros.x0, end_label)
        
        asm.label(name)
        
        old_depth = self.current_stack_depth
        self.current_stack_depth = 0  
        self.enter_scope()
        
        arg_offset = -4 
        for arg in reversed(block_node.args):
            info = SymbolInfo(
                offset_from_base=arg_offset, 
                is_function=False, 
                arg_count=0
            )
            self.scopes[-1][arg] = info
            arg_offset -= 4

        for child in block_node.children:
            self._compile_node(child)
            
        asm.addi(macros.a0, macros.x0, 0)
        if self.current_stack_depth > 0:
            asm.addi(macros.stack_ptr, macros.stack_ptr, -self.current_stack_depth)
        asm.jalr(macros.x0, macros.ra, 0)
            
        self.exit_scope()
        self.current_stack_depth = old_depth
        asm.label(end_label)
    def _evaluate_comptime(self, node: ExprNode) -> int:
        """Evaluates an AST math expression during compilation."""
        if node.type == ExprNodeType.Value:
            return node.value.value
        elif node.type == ExprNodeType.BinaryOp:
            left = self._evaluate_comptime(node.left)
            right = self._evaluate_comptime(node.right)
            op = node.value.value
            if op == "+": 
                return left + right
            if op == "-": 
                return left - right
            if op == "*": 
                return left * right
            if op == "/": 
                return left // right
        raise ValueError(f"Space slice [:expr] must be a compile-time constant. Got: {node.type}")
    
    def _compile_expr(self, node: ExprNode):
        match node.type:
            case ExprNodeType.Macro:
                macro_name = node.value.value
                
                if macro_name == "embed":
                    # Spite string literals. Build string backwards from the tokens!
                    path = "".join(str(t.value) for t in node.children)
                    with open(path, "rb") as f:
                        data = f.read()
                        
                    skip_label = self.get_unique_label("skip_embed")
                    # jal rd, offset assigns the address of the NEXT instruction to rd
                    # which happens to be exactly where our raw bytes start! 
                    asm.jal(macros.t0, skip_label)
                    
                    # Dump bytes straight into the code segment
                    asm.code.extend(data)
                    
                    # Instruction Alignment constraint padding (ensure future instructions don't misalign)
                    padding = (4 - (len(data) % 4)) % 4
                    if padding > 0:
                        asm.code.extend(b'\x00' * padding)
                        
                    asm.label(skip_label)
                    
                    macros.push(macros.t0)
                    self.current_stack_depth += 4
                    return None
                    
                elif macro_name == "import":
                    raise SyntaxError("@import can only be used as a namespace assignment (e.g. math = @import(math.w))")
                    
                elif macro_name == "asm":
                    inst_name = node.children[0].value
                    args =[]
                    
                    reg_map = macros.reg_map
                    no_rd_instructions = {"store", "bge", "beq", "bne", "ecall"}
                    has_rd = inst_name not in no_rd_instructions
                    
                    temp_pool =[6, 7, 11, 12, 13, 14]
                    temp_idx = 0
                    
                    store_back_sym = None
                    rd_reg_to_push = 0
                    
                    for i, child in enumerate(node.children[1:]):
                        if isinstance(child, Identifier):
                            name = child.value
                            if name in reg_map:
                                args.append(reg_map[name])
                                if i == 0 and has_rd:
                                    rd_reg_to_push = reg_map[name]
                            else:
                                sym = self.get_symbol(name)
                                is_output = (i == 0 and has_rd)
                                
                                if is_output:
                                    if not sym:
                                        macros.push(macros.x0)
                                        self.current_stack_depth += 4
                                        sym = self.declare_symbol(name)
                                    
                                    args.append(5)
                                    store_back_sym = sym
                                    rd_reg_to_push = 5
                                else:
                                    if not sym:
                                        raise ValueError(f"Undefined variable read in @asm: {name}")
                                    
                                    if temp_idx >= len(temp_pool):
                                        raise ValueError("Too many memory variables in @asm block.")
                                    tmp_reg = temp_pool[temp_idx]
                                    temp_idx += 1
                                    
                                    offset = sym.offset_from_base - self.current_stack_depth
                                    asm.load(tmp_reg, macros.stack_ptr, offset)
                                    args.append(tmp_reg)
                                    
                        elif isinstance(child, Value):
                            args.append(child.value)
                            
                    asm_method = getattr(asm, inst_name)
                    asm_method(*args)
                    
                    if store_back_sym:
                        offset = store_back_sym.offset_from_base - self.current_stack_depth
                        asm.store(macros.stack_ptr, offset, macros.t0) 
                    
                    macros.push(rd_reg_to_push)
                    self.current_stack_depth += 4
                    return None
                    
                else:
                    raise SyntaxError(f"Unknown macro @{macro_name}")

            case ExprNodeType.Value:
                macros.push_value(node.value.value)
                self.current_stack_depth += 4
            case ExprNodeType.Deref:
                self._compile_expr(node.left)
                macros.pop(macros.t0) 
                asm.load(macros.t1, macros.t0, 0)
                macros.push(macros.t1)
            case ExprNodeType.Identifier:
                sym = self.get_symbol(node.value.value)
                if not sym: 
                    raise ValueError(f"Undefined variable: {node.value.value}")
                
                offset = (sym.offset_from_base - self.current_stack_depth) 
                asm.load(macros.t0, macros.stack_ptr, offset) 
                macros.push(macros.t0)
                self.current_stack_depth += 4
                return sym.type_name

            case ExprNodeType.BinaryOp:
                self._compile_expr(node.left)
                self._compile_expr(node.right)
                
                macros.pop(macros.t1)
                macros.pop(macros.t0)
                self.current_stack_depth -= 8
                
                op_sym = node.value.value
                if op_sym == "+":
                    asm.add(macros.t0, macros.t0, macros.t1)
                elif op_sym == "-":
                    asm.sub(macros.t0, macros.t0, macros.t1)
                elif op_sym == "==":
                    asm.sub(macros.t0, macros.t0, macros.t1)
                    asm.sltiu(macros.t0, macros.t0, 1)     
                elif op_sym == "!=":
                    asm.sub(macros.t0, macros.t0, macros.t1)
                    asm.sltu(macros.t0, macros.x0, macros.t0) 
                elif op_sym == "<":
                    asm.slt(macros.t0, macros.t0, macros.t1)
                elif op_sym == ">":
                    asm.slt(macros.t0, macros.t1, macros.t0)
                elif op_sym == "<=":
                    asm.slt(macros.t0, macros.t1, macros.t0) 
                    asm.xori(macros.t0, macros.t0, 1)        
                elif op_sym == ">=":
                    asm.slt(macros.t0, macros.t0, macros.t1) 
                    asm.xori(macros.t0, macros.t0, 1)        
                else:
                    raise SyntaxError(f"operand definition for {op_sym} was not found")
                
                macros.push(macros.t0)
                self.current_stack_depth += 4

            case ExprNodeType.Call:
                func_name = node.value.value
                
                # 1. Is it an Object Spawn? (Type Instantiation)
                if func_name in self.types:
                    if not node.children: raise ValueError(f"Instantiation {func_name} requires an allocation argument.")
                    self._compile_expr(node.children[0]) # Evaluates the memory slice, leaving pointer on stack
                    return func_name # Returns the type name to the Assigner!
                    
                # 2. Is it a Method Call?
                if "." in func_name:
                    base_var, method = func_name.split(".", 1)
                    sym = self.get_symbol(base_var)
                    if not sym or not sym.type_name:
                        raise ValueError(f"Cannot resolve method {func_name}. Variable '{base_var}' has no known type.")
                        
                    type_info = self.types.get(sym.type_name)
                    if not type_info or method not in type_info["methods"]:
                        raise ValueError(f"Type '{sym.type_name}' has no method '{method}'")
                        
                    real_func_name = type_info["methods"][method]
                    
                    asm.addi(macros.t0, macros.ra, 0)
                    macros.push(macros.t0)
                    self.current_stack_depth += 4
                    
                    # Push `self` as the implicit first argument!
                    offset = (sym.offset_from_base - self.current_stack_depth)
                    asm.load(macros.t0, macros.stack_ptr, offset)
                    macros.push(macros.t0)
                    self.current_stack_depth += 4
                    
                    for arg in node.children:
                        self._compile_expr(arg)
                        
                    asm.jal(macros.ra, real_func_name)
                    asm.addi(macros.t2, macros.a0, 0) 
                    
                    # Pop arguments PLUS the implicit `self`
                    for _ in range(len(node.children) + 1):
                         macros.pop(macros.x0) 
                         self.current_stack_depth -= 4
                    
                    macros.pop(macros.ra)
                    self.current_stack_depth -= 4
                    
                    macros.push(macros.t2)
                    self.current_stack_depth += 4
                    return None
                asm.addi(macros.t0, macros.ra, 0)
                macros.push(macros.t0)
                self.current_stack_depth += 4

                for arg in node.children:
                    self._compile_expr(arg)
                
                asm.jal(macros.ra, func_name)
                asm.addi(macros.t2, macros.a0, 0) 

                for _ in node.children:
                     macros.pop(macros.x0) 
                     self.current_stack_depth -= 4
                
                macros.pop(macros.ra)
                self.current_stack_depth -= 4
                
                macros.push(macros.t2)
                self.current_stack_depth += 4

            case ExprNodeType.ArrayAlloc:
                size = self._evaluate_comptime(node.left) 
                macros.push(macros.stack_ptr) 
                self.current_stack_depth += 4
                
                # Raw bytes allocation instead of size * 4
                asm.addi(macros.stack_ptr, macros.stack_ptr, size)
                self.current_stack_depth += size