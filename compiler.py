
import macros
from macros import asm
from AST import NodeType, ASTNode
from expression import ExprNodeType, ExprNode
from typing import Dict, Optional, List
from dataclasses import dataclass, field
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
    return_type: str = ""
    
    variants: list = field(default_factory=list) # Stores all overload AST nodes
    is_compiled: bool = False                    # Prevents double-compilation

class Compiler:
    def __init__(self):
        self.scopes: List[Dict[str, SymbolInfo]] = [{}]
        self.types = {} 
        self.current_stack_depth = 0
        self.label_counter = 0

    def get_symbol(self, name: str) -> Optional[SymbolInfo]:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def declare_symbol(self, name: str, is_fn=False, args=0, type_name=""):
        info = SymbolInfo(offset_from_base=self.current_stack_depth - asm.REGISTER_SIZE,
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

    def Return(self, node):
        if node.children:
            child = node.children[0]
            if child.node_type == NodeType.Expression:
                self._compile_expr(child.expr)
            else:
                self._compile_node(child)
                
            macros.pop(macros.t0) 
            self.current_stack_depth -= asm.REGISTER_SIZE
            asm.addi(macros.a0, macros.t0, 0)
        else:
            asm.addi(macros.a0, macros.x0, 0)
            
        if self.current_stack_depth > 0:
            asm.addi(macros.stack_ptr, macros.stack_ptr, -self.current_stack_depth)

        asm.jalr(macros.x0, macros.ra, 0)

    def Expression(self, node):
        if node.expr:
            self._compile_expr(node.expr)
            macros.pop(macros.t0)
            self.current_stack_depth -= asm.REGISTER_SIZE

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
            
        diff = self.current_stack_depth - start_depth
        if diff > 0:
            asm.addi(macros.stack_ptr, macros.stack_ptr, -diff)
            self.current_stack_depth = start_depth
            
        # Compile any functions declared locally in this block
        funcs = {k:v for k,v in self.scopes[-1].items() if v.is_function and not getattr(v, 'is_compiled', False)}
        if funcs:
            skip_lbl = self.get_unique_label("skip_funcs")
            asm.jal(macros.x0, skip_lbl) # Jump over the function bodies
            self._compile_scope_functions(funcs)
            asm.label(skip_lbl)
            
        self.exit_scope()
    
    def _handle_import(self, namespace: str, filepath: str):
        with open(filepath, 'r') as f:
            source = f.read()
            
        imported_tokens = tokens.tokenize(source)
        imported_ast = AST.parse(imported_tokens)
        
        top_level_names = set()
        for node in imported_ast.children:
            if getattr(node, 'identifier', None):
                top_level_names.add(node.identifier)
                
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
                    for i, arg in enumerate(node.children):
                        for j, child in enumerate(arg):
                            if isinstance(child, tokens.Identifier) and child.value in top_level_names:
                                node.children[i][j] = tokens.Identifier(f"{namespace}.{child.value}")
                            
                for child in node.children:
                    if isinstance(child, (AST.ASTNode, expression.ExprNode)):
                        replace_names(child)
                if node.left: replace_names(node.left)
                if node.right: replace_names(node.right)

        replace_names(imported_ast)
        for child in imported_ast.children:
            self._compile_node(child)

    def Pipeline(self, node):
        name = node.identifier
        
        # Apply current type context mapping to dot prefixes (e.g., .func -> int.func)
        if name and name.startswith(".") and getattr(self, 'current_type_context', None):
            name = self.current_type_context + name
            node.identifier = name
            
        bindings = node.children[0].children 
        body = node.children[1]
        loop_type_name = getattr(node, "type_name", "")
        outputs = getattr(node, "outputs",[])
        
        # Synthesize Return output natively based on declared Outputs signature
        ret_node = None
        if outputs:
            out_name = outputs[0]["name"]
            if out_name:
                ret_expr = ExprNode(ExprNodeType.Identifier, value=Identifier(out_name))
                ret_node = ASTNode(NodeType.Return)
                ret_node.children.append(ASTNode(NodeType.Expression, expr=ret_expr))

        # 1. Is it a Type Definition? (e.g., int : value = (bytes[:4]))
        is_type = False
        comptime_size = 0
        if bindings and getattr(bindings[0], "is_type", False):
            is_type = True
            comptime_size = self._evaluate_comptime(bindings[0].expr)

        if is_type:
            self.types[name] = {"size": comptime_size, "methods": {}, "fields": {}, "statics": {}}
            prev_type = getattr(self, 'current_type_context', None)
            prev_blueprint = getattr(self, 'current_blueprint_context', None)
            
            self.current_type_context = name
            self.current_blueprint_context = outputs[0]["name"] if outputs and outputs[0]["name"] else "value"
            
            self.enter_scope()
            base_ident = bindings[0].identifier
            self.declare_symbol(base_ident, type_name="bytes")
            
            for child in body.children:
                self._compile_node(child)
                
            self.exit_scope()
            self.current_type_context = prev_type
            self.current_blueprint_context = prev_blueprint
            return

        # 2. Is it a Method / Function?
        is_loop = False
        for b in bindings:
            if b.expr and b.expr.type == ExprNodeType.BinaryOp and b.expr.value.value == ":":
                is_loop = True
                
        if not is_loop and (outputs or self.current_stack_depth == 0 or getattr(self, 'current_type_context', None)):
            func_name = name
            if getattr(self, 'current_type_context', None):
                type_name = self.current_type_context
                # Strip the prefix to get the clean method name (e.g. int.__op_+ -> __op_+)
                if name.startswith(f"{type_name}."):
                    method_name = name[len(type_name)+1:]
                else:
                    method_name = name.split(".")[-1]
                    
                func_name = f"__{type_name}_{method_name}"
                self.types[type_name]["methods"][method_name] = func_name
                
            # Only check the LOCAL scope so local overloads shadow global functions cleanly
            sym = self.scopes[-1].get(func_name)
            if not sym:
                sym = self.declare_symbol(func_name, is_fn=True)
            if outputs:
                sym.return_type = outputs[0]["type"]
                
            # Add this overload as a variant and delay compilation
            sym.variants.append({
                "bindings": bindings,
                "body": body,
                "ret_node": ret_node,
                "outputs": outputs
            })
            return

        # 3. Otherwise, it's a Runtime Loop / Temporal Pipeline!
        self._compile_loop(name, bindings, body, loop_type_name)

    def StoreOrAssign(self, node):
        name = node.identifier
        
        if name and name.startswith(".") and getattr(self, 'current_type_context', None):
            name = self.current_type_context + name
            node.identifier = name
            
        idx_name = getattr(node, "type_name", "")
        
        if idx_name == "" or idx_name in self.types or not self.get_symbol(name):
            node.node_type = NodeType.Assignment
            return self.Assignment(node)
        else:
            node.node_type = NodeType.Store
            ptr_expr = ExprNode(ExprNodeType.BinaryOp, value=Symbol("+"),
                                left=ExprNode(ExprNodeType.Identifier, value=Identifier(name)),
                                right=ExprNode(ExprNodeType.Identifier, value=Identifier(idx_name)))
            node.children.insert(0, ASTNode(NodeType.Expression, expr=ptr_expr))
            return self.Store(node)

    def Assignment(self, node):
        name = node.identifier
        
        if name and name.startswith(".") and getattr(self, 'current_type_context', None):
            name = self.current_type_context + name
            node.identifier = name
            
        if node.children and node.children[0].node_type == NodeType.Expression:
            child = node.children[0]
            
            # 1. Handle Import Macro
            if child.expr and child.expr.type == ExprNodeType.Macro and child.expr.value.value == "import":
                path = "".join(str(t.value) for arg in child.expr.children for t in arg)
                self._handle_import(name, path)
                return

            # 2. Handle Namespace / Type Aliasing (e.g., math = fd.math or int = td.int)
            if child.expr and child.expr.type == ExprNodeType.Identifier:
                rhs_name = child.expr.value.value
                rhs_prefix = rhs_name + "."
                lhs_prefix = name + "."
                aliased = False
                
                # Copy Types
                types_to_add = {}
                for t_name, t_info in self.types.items():
                    if t_name == rhs_name:
                        types_to_add[name] = t_info
                        aliased = True
                    elif t_name.startswith(rhs_prefix):
                        new_t_name = lhs_prefix + t_name[len(rhs_prefix):]
                        types_to_add[new_t_name] = t_info
                        aliased = True
                self.types.update(types_to_add)
                
                # Copy Functions (from global scope)
                funcs_to_add = {}
                for s_name, s_info in self.scopes[0].items():
                    if s_name == rhs_name:
                        funcs_to_add[name] = s_info
                        aliased = True
                    elif s_name.startswith(rhs_prefix):
                        new_s_name = lhs_prefix + s_name[len(rhs_prefix):]
                        funcs_to_add[new_s_name] = s_info
                        aliased = True
                self.scopes[0].update(funcs_to_add)
                
                if aliased:
                    return 
                    
        # Are we building a Type?
        if getattr(self, 'current_type_context', None):
            type_name = self.current_type_context
            blueprint = getattr(self, 'current_blueprint_context', "value")
            
            if node.children and node.children[0].node_type == NodeType.Expression:
                val = self._evaluate_comptime(node.children[0].expr)
                
                # Check namespace explicitly!
                if name.startswith(f"{type_name}."):
                    static_name = name[len(type_name)+1:]
                    self.types[type_name]["statics"][static_name] = val
                elif name.startswith(f"{blueprint}.") or name == blueprint:
                    field_name = name[len(blueprint)+1:] if name != blueprint else "self"
                    self.types[type_name]["fields"][field_name] = val
                else:
                    raise ValueError(f"Ambiguous assignment inside Type {type_name}. Must start with '{type_name}.' or '{blueprint}.'")
            return
            
        # 3. Regular Variable Assignment
        if node.children and node.children[0].node_type == NodeType.Expression:
            self._compile_expr(node.children[0].expr)
            sym = self.get_symbol(name)
            if not sym:
                self.declare_symbol(name, type_name=getattr(node, "type_name", ""))
            else:
                macros.pop(macros.t0)
                self.current_stack_depth -= asm.REGISTER_SIZE
                offset = sym.offset_from_base - self.current_stack_depth
                asm.store(macros.stack_ptr, offset, macros.t0)
    
    def Store(self, node):
        val_type = self._compile_expr(node.children[1].expr)
        ptr_type = self._compile_expr(node.children[0].expr)
        
        macros.pop(macros.t0) # ptr
        macros.pop(macros.t1) # val
        self.current_stack_depth -= asm.REGISTER_SIZE * 2
        
        size = asm.REGISTER_SIZE
        if val_type and val_type in self.types:
            size = self.types[val_type].get("size", asm.REGISTER_SIZE)
            
        if size == 1:
            asm.sb(macros.t0, 0, macros.t1)
        elif size == 2:
            asm.sh(macros.t0, 0, macros.t1)
        else:
            asm.sw(macros.t0, 0, macros.t1)

    def Deref(self, node, expected_type=None):
        self._compile_expr(node.left)
        macros.pop(macros.t0) 
        
        size = asm.REGISTER_SIZE
        if expected_type and expected_type in self.types:
            size = self.types[expected_type].get("size", asm.REGISTER_SIZE)
            
        if size == 1:
            asm.lbu(macros.t1, macros.t0, 0)
        elif size == 2:
            asm.lhu(macros.t1, macros.t0, 0)
        else:
            asm.lw(macros.t1, macros.t0, 0)
            
        macros.push(macros.t1)
        return expected_type

    def Program(self, node):
        for child in node.children:
            self._compile_node(child)
        asm.ecall()
        self._compile_scope_functions(self.scopes[0])

    def _compile_scope_functions(self, scope_dict):
        for name, sym in scope_dict.items():
            if sym.is_function and sym.variants and not sym.is_compiled:
                self._emit_multifunction_dispatcher(name, sym)
                sym.is_compiled = True

    def _emit_multifunction_dispatcher(self, func_name: str, sym: SymbolInfo):
        asm.label(func_name)
        old_depth = self.current_stack_depth
        self.current_stack_depth = 0  
        
        # Temporarily clear context so we are compiling a runtime method body
        old_type_ctx = getattr(self, 'current_type_context', None)
        old_blueprint_ctx = getattr(self, 'current_blueprint_context', None)
        self.current_type_context = None
        self.current_blueprint_context = None

        for idx, variant in enumerate(sym.variants):
            bindings = variant["bindings"]
            body = variant["body"]
            ret_node = variant["ret_node"]
            outputs = variant["outputs"]
            
            next_variant_lbl = self.get_unique_label(f"next_var_{func_name}")
            
            self.enter_scope()
            
            # Setup argument mappings from the caller's stack
            arg_offset = -asm.REGISTER_SIZE
            for i in reversed(range(len(bindings))):
                binding = bindings[i]
                info = SymbolInfo(
                    offset_from_base=arg_offset, 
                    is_function=False, 
                    arg_count=0,
                    type_name=getattr(binding, "type_name", "")
                )
                self.scopes[-1][binding.identifier] = info
                arg_offset -= asm.REGISTER_SIZE

            # -------------------------------------------------------------
            # PATTERN MATCHING: Check all constraints (e.g. x==1)
            # -------------------------------------------------------------
            for binding in bindings:
                if binding.expr:
                    self._compile_expr(binding.expr)
                    macros.pop(macros.t0)
                    self.current_stack_depth -= asm.REGISTER_SIZE
                    # If the condition evaluated to 0 (False), Jump to the next Variant!
                    asm.beq(macros.t0, macros.x0, next_variant_lbl)

            # --- If we made it here, the Pattern Matched! ---

            # Automatically Allocate Output Arguments
            if outputs:
                for out in outputs:
                    if out["name"]:
                        macros.push(macros.x0)
                        self.current_stack_depth += asm.REGISTER_SIZE
                        out_sym = self.declare_symbol(out["name"], type_name=out["type"])
                        out_sym.return_type = out["type"]

            # Compile Body
            for child in body.children:
                self._compile_node(child)
                
            if ret_node:
                self._compile_expr(ret_node.children[0].expr)
                macros.pop(macros.t0)
                self.current_stack_depth -= asm.REGISTER_SIZE  
                asm.addi(macros.a0, macros.t0, 0)
            else:
                asm.addi(macros.a0, macros.x0, 0)
                
            if self.current_stack_depth > 0:
                asm.addi(macros.stack_ptr, macros.stack_ptr, -self.current_stack_depth)
                
            # Exit Function!
            asm.jalr(macros.x0, macros.ra, 0)
                
            self.exit_scope()
            self.current_stack_depth = 0 # Reset depth for the next variant block
            
            # Label for the next variant fallback
            asm.label(next_variant_lbl)

        # -------------------------------------------------------------
        # PANIC: If execution falls down here, NO variants matched!
        # -------------------------------------------------------------
        #TODO sanitycheck, do i even want to crash here?
        asm.ecall()

        # Restore contexts
        self.current_stack_depth = old_depth
        self.current_type_context = old_type_ctx
        self.current_blueprint_context = old_blueprint_ctx

    def _compile_loop(self, name, bindings, body, loop_type_name=""):
        out_sym = self.get_symbol(name)
        if not out_sym:
            out_sym = self.declare_symbol(name, type_name=loop_type_name)
            macros.push(macros.x0)
            self.current_stack_depth += asm.REGISTER_SIZE
            
        l_start = self.get_unique_label("loop_start")
        l_end = self.get_unique_label("loop_end")
        
        self.enter_scope()
        start_depth = self.current_stack_depth
        
        # Temporarily clear context so we are compiling a runtime loop body
        old_type_ctx = getattr(self, 'current_type_context', None)
        old_blueprint_ctx = getattr(self, 'current_blueprint_context', None)
        self.current_type_context = None
        self.current_blueprint_context = None
        
        range_var = None
        range_end_expr = None
        
        for b in bindings:
            if b.expr and b.expr.type == ExprNodeType.BinaryOp and b.expr.value.value == ":":
                range_var = b.identifier
                self._compile_expr(b.expr.left)
                range_end_expr = b.expr.right
                self.declare_symbol(b.identifier, type_name=getattr(b, "type_name", ""))
            elif b.expr:
                self._compile_expr(b.expr)
                self.declare_symbol(b.identifier, type_name=getattr(b, "type_name", ""))
            else:
                macros.push(macros.x0)
                self.current_stack_depth += asm.REGISTER_SIZE
                self.declare_symbol(b.identifier, type_name=getattr(b, "type_name", ""))
                
        if range_end_expr:
            self._compile_expr(range_end_expr)
            end_limit_sym = self.declare_symbol(f"__end_limit_{range_var}")
            
        asm.label(l_start)
        
        if range_var and range_end_expr:
            var_info = self.get_symbol(range_var)
            end_info = self.get_symbol(f"__end_limit_{range_var}")
            asm.lw(macros.t0, macros.stack_ptr, var_info.offset_from_base - self.current_stack_depth)
            asm.lw(macros.t1, macros.stack_ptr, end_info.offset_from_base - self.current_stack_depth)
            asm.bge(macros.t0, macros.t1, l_end)
            
        self._compile_node(body)
                
        if range_var:
            var_info = self.get_symbol(range_var)
            asm.lw(macros.t0, macros.stack_ptr, var_info.offset_from_base - self.current_stack_depth)
            asm.addi(macros.t0, macros.t0, 1)
            asm.sw(macros.stack_ptr, var_info.offset_from_base - self.current_stack_depth, macros.t0)
          
        asm.jal(macros.x0, l_start)
        asm.label(l_end)
        
        # Free memory tied to local context loop variables to prevent stack offsets growing infinitely in blocks
        diff = self.current_stack_depth - start_depth
        if diff > 0:
            asm.addi(macros.stack_ptr, macros.stack_ptr, -diff)
            self.current_stack_depth = start_depth
            
        self.exit_scope()

        # Restore context 
        self.current_type_context = old_type_ctx
        self.current_blueprint_context = old_blueprint_ctx

    def _evaluate_comptime(self, node: ExprNode) -> int:
        if node.type == ExprNodeType.Value:
            return node.value.value
        elif node.type == ExprNodeType.Identifier:
            return 0  
        elif node.type == ExprNodeType.BinaryOp:
            left = self._evaluate_comptime(node.left)
            right = self._evaluate_comptime(node.right)
            op = node.value.value
            if op == "+": return left + right
            if op == "-": return left - right
            if op == "*": return left * right
            if op == "/": return left // right
            if op == ":": return left 
        elif node.type == ExprNodeType.Deref:
            # Passes down Deref structures like `bytes[4:8]`
            return self._evaluate_comptime(node.left)
        raise ValueError("Space slice [:expr] must be a compile-time constant.")
    
    def _compile_expr(self, node: ExprNode, expected_type=None):
        match node.type:
            case ExprNodeType.Macro:
                macro_name = node.value.value
                
                if macro_name == "embed":
                    path = "".join(str(t.value) for arg in node.children for t in arg)
                    with open(path, "rb") as f:
                        data = f.read()
                        
                    skip_label = self.get_unique_label("skip_embed")
                    asm.jal(macros.t0, skip_label)
                    
                    asm.code.extend(data)
                    padding = (asm.REGISTER_SIZE - (len(data) % asm.REGISTER_SIZE)) % asm.REGISTER_SIZE
                    if padding > 0:
                        asm.code.extend(b'\x00' * padding)
                        
                    asm.label(skip_label)
                    
                    macros.push(macros.t0)
                    self.current_stack_depth += asm.REGISTER_SIZE
                    return None
                    
                elif macro_name == "import":
                    raise SyntaxError("@import can only be used as a namespace assignment (e.g. math = @import(math.w))")
                    
                elif macro_name == "asm":
                    inst_toks = node.children[0]
                    inst_name = inst_toks[0].value
                    args =[]
                    
                    reg_map = macros.reg_map
                    no_rd_instructions = {"store", "sw", "sb", "bge", "beq", "bne", "ecall"}
                    has_rd = inst_name not in no_rd_instructions
                    
                    temp_pool =[6, 7, 11, 12, 13, 14]
                    temp_idx = 0
                    
                    store_back_sym = None
                    rd_reg_to_push = 0
                    
                    for i, arg_toks in enumerate(node.children[1:]):
                        if not arg_toks: continue
                        
                        if len(arg_toks) == 1 and isinstance(arg_toks[0], Value):
                            args.append(arg_toks[0].value)
                            continue
                            
                        name = arg_toks[0].value
                        type_name = ""
                        if len(arg_toks) >= 4 and arg_toks[1] == Symbol("[") and isinstance(arg_toks[2], Identifier):
                            type_name = arg_toks[2].value
                            
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
                                    self.current_stack_depth += asm.REGISTER_SIZE
                                    sym = self.declare_symbol(name, type_name=type_name)
                                elif type_name and not sym.type_name:
                                    sym.type_name = type_name
                                
                                args.append(5) 
                                store_back_sym = sym
                                rd_reg_to_push = 5
                            else:
                                if not sym:
                                    raise ValueError(f"Undefined variable read in @asm: {name}")
                                
                                tmp_reg = temp_pool[temp_idx]
                                temp_idx += 1
                                
                                offset = sym.offset_from_base - self.current_stack_depth
                                asm.load(tmp_reg, macros.stack_ptr, offset)
                                args.append(tmp_reg)
                    
                    asm_method = getattr(asm, inst_name)
                    asm_method(*args)
                    
                    if store_back_sym:
                        offset = store_back_sym.offset_from_base - self.current_stack_depth
                        asm.store(macros.stack_ptr, offset, macros.t0) 
                    
                    macros.push(rd_reg_to_push)
                    self.current_stack_depth += asm.REGISTER_SIZE
                    return None
                else:
                    raise SyntaxError(f"Unknown macro @{macro_name}")

            case ExprNodeType.Value:
                macros.push_value(node.value.value)
                self.current_stack_depth += asm.REGISTER_SIZE
                
            case ExprNodeType.Deref:
                return self.Deref(node, expected_type)
                
            case ExprNodeType.Identifier:
                var_name = node.value.value
                
                # Context-prefixed identifiers (e.g. `.max` -> `int.max`)
                if var_name.startswith(".") and getattr(self, 'current_type_context', None):
                    var_name = self.current_type_context + var_name
                    
                if "." in var_name:
                    base_name, field_name = var_name.split(".", 1)
                    
                    # 1. Type Constant / Static? (Reads from our 'statics' dict)
                    if base_name in self.types and field_name in self.types[base_name].get("statics", {}):
                        val = self.types[base_name]["statics"][field_name]
                        macros.push_value(val)
                        self.current_stack_depth += asm.REGISTER_SIZE
                        return None
                        
                    # 2. Instance Memory Read
                    sym = self.get_symbol(base_name)
                    if not sym: 
                        raise ValueError(f"Undefined variable: {base_name}")
                        
                    if sym.type_name in self.types and field_name in self.types[sym.type_name].get("fields", {}):
                        offset_val = self.types[sym.type_name]["fields"][field_name]
                        ptr_offset = (sym.offset_from_base - self.current_stack_depth)
                        
                        asm.lw(macros.t0, macros.stack_ptr, ptr_offset)
                        asm.lw(macros.t1, macros.t0, offset_val)        
                        
                        macros.push(macros.t1)
                        self.current_stack_depth += asm.REGISTER_SIZE
                        return None
                        
                    raise ValueError(f"Cannot read field '{field_name}' on '{base_name}'")

                # Standard variable read
                sym = self.get_symbol(var_name)
                if not sym: 
                    raise ValueError(f"Undefined variable: {var_name}")
                
                offset = (sym.offset_from_base - self.current_stack_depth) 
                asm.lw(macros.t0, macros.stack_ptr, offset) 
                macros.push(macros.t0)
                self.current_stack_depth += asm.REGISTER_SIZE
                return sym.type_name


            case ExprNodeType.BinaryOp:
                left_type = self._compile_expr(node.left)
                op_sym = node.value.value
                
                if left_type and left_type in self.types:
                    type_info = self.types[left_type]
                    method_name = f"__op_{op_sym}"
                    
                    if method_name in type_info.get("methods", {}):
                        func_name = type_info["methods"][method_name]
                        
                        self._compile_expr(node.right)
                        macros.pop(macros.t1) 
                        macros.pop(macros.t0) 
                        self.current_stack_depth -= asm.REGISTER_SIZE*2
                        
                        asm.addi(macros.t2, macros.ra, 0)
                        macros.push(macros.t2)
                        self.current_stack_depth += asm.REGISTER_SIZE
                        
                        macros.push(macros.t0)
                        macros.push(macros.t1)
                        self.current_stack_depth += asm.REGISTER_SIZE*2
                        
                        asm.jal(macros.ra, func_name)
                        asm.addi(macros.t2, macros.a0, 0)
                        
                        macros.pop(macros.x0)
                        macros.pop(macros.x0)
                        self.current_stack_depth -= asm.REGISTER_SIZE*2
                        
                        macros.pop(macros.ra)
                        self.current_stack_depth -= asm.REGISTER_SIZE
                        
                        macros.push(macros.t2)
                        self.current_stack_depth += asm.REGISTER_SIZE
                        return left_type 
                    
                self._compile_expr(node.right)
                macros.pop(macros.t1)
                macros.pop(macros.t0)
                self.current_stack_depth -= asm.REGISTER_SIZE*2
                
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
                self.current_stack_depth += asm.REGISTER_SIZE

            case ExprNodeType.Call:
                func_name = node.value.value
                
                # Context-prefixed methods (e.g. `.sum_n()`)
                if func_name.startswith(".") and getattr(self, 'current_type_context', None):
                    func_name = self.current_type_context + func_name
                
                if func_name in self.types:
                    if not node.children: raise ValueError(f"Instantiation {func_name} requires an allocation argument.")
                    self._compile_expr(node.children[0]) 
                    return func_name 
                    
                # 1. Check if it's a Static Namespace/Type Function (Without requiring self-ptr instantiation)
                if "." in func_name:
                    base_var, method = func_name.split(".", 1)
                    if base_var in self.types and method in self.types[base_var].get("methods", {}):
                        real_func_name = self.types[base_var]["methods"][method]
                        
                        asm.addi(macros.t0, macros.ra, 0)
                        macros.push(macros.t0)
                        self.current_stack_depth += asm.REGISTER_SIZE
                        
                        for arg in node.children:
                            self._compile_expr(arg)
                            
                        asm.jal(macros.ra, real_func_name)
                        asm.addi(macros.t2, macros.a0, 0) 
                        
                        for _ in node.children:
                             macros.pop(macros.x0) 
                             self.current_stack_depth -= asm.REGISTER_SIZE
                        
                        macros.pop(macros.ra)
                        self.current_stack_depth -= asm.REGISTER_SIZE
                        
                        macros.push(macros.t2)
                        self.current_stack_depth += asm.REGISTER_SIZE
                        
                        sym = self.get_symbol(real_func_name)
                        if sym and sym.return_type:
                            return sym.return_type
                        return "byte"
                
                # 2. Check if it's an Instance Method (Requires initialized local pointer)
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
                    self.current_stack_depth += asm.REGISTER_SIZE
                    
                    offset = (sym.offset_from_base - self.current_stack_depth)
                    asm.lw(macros.t0, macros.stack_ptr, offset)
                    macros.push(macros.t0)
                    self.current_stack_depth += asm.REGISTER_SIZE
                    
                    for arg in node.children:
                        self._compile_expr(arg)
                        
                    asm.jal(macros.ra, real_func_name)
                    asm.addi(macros.t2, macros.a0, 0) 
                    
                    # Pop arguments + instance pointer
                    for _ in range(len(node.children) + 1):
                         macros.pop(macros.x0) 
                         self.current_stack_depth -= asm.REGISTER_SIZE
                    
                    macros.pop(macros.ra)
                    self.current_stack_depth -= asm.REGISTER_SIZE
                    
                    macros.push(macros.t2)
                    self.current_stack_depth += asm.REGISTER_SIZE
                    return None

                # 3. Global / Local Function Call
                sym = self.get_symbol(func_name)
                if sym and sym.is_function:
                    asm.addi(macros.t0, macros.ra, 0)
                    macros.push(macros.t0)
                    self.current_stack_depth += asm.REGISTER_SIZE
                    
                    for arg in node.children:
                        self._compile_expr(arg)
                        
                    asm.jal(macros.ra, func_name)
                    asm.addi(macros.t2, macros.a0, 0) 
                    
                    for _ in node.children:
                         macros.pop(macros.x0) 
                         self.current_stack_depth -= asm.REGISTER_SIZE
                    
                    macros.pop(macros.ra)
                    self.current_stack_depth -= asm.REGISTER_SIZE
                    
                    macros.push(macros.t2)
                    self.current_stack_depth += asm.REGISTER_SIZE
                    return sym.return_type

                if "." not in func_name:
                    raise ValueError(f"Undefined function '{func_name}'")
            case ExprNodeType.ArrayAlloc:
                if node.left:
                    size = self._evaluate_comptime(node.left)
                elif node.value:
                    if hasattr(node.value, "value"):
                        size = int(node.value.value)
                    else:
                        size = int(node.value)
                else:
                    size = 0
                    
                # Allocate space FIRST 
                asm.addi(macros.stack_ptr, macros.stack_ptr, size)
                self.current_stack_depth += size
                
                # Calculate the start pointer (stack_ptr - size)
                asm.addi(macros.t0, macros.stack_ptr, -size)
                
                # Push the start pointer to the stack (so it points to the beginning of the newly allocated space)
                macros.push(macros.t0)
                self.current_stack_depth += asm.REGISTER_SIZE
