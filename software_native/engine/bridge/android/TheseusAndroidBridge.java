// Theseus-owned static Android reader using the installed JADX library API.
import com.google.gson.*;
import jadx.api.*;
import jadx.api.plugins.input.insns.InsnIndexType;
import jadx.core.dex.info.MethodInfo;
import jadx.core.dex.nodes.*;
import java.nio.file.*;
import java.math.BigInteger;
import java.util.*;
import java.util.stream.Collectors;

public class TheseusAndroidBridge {
    static final Gson JSON = new GsonBuilder().setPrettyPrinting().serializeNulls().create();
    static Map<String,Object> row(Object... pairs) {
        Map<String,Object> result = new LinkedHashMap<>();
        for (int i=0;i<pairs.length;i+=2) result.put((String)pairs[i], pairs[i+1]);
        return result;
    }
    static String text(JsonObject p,String key,String fallback) {
        return p.has(key) ? p.get(key).getAsString() : fallback;
    }
    static int number(JsonObject p,String key,int fallback) {
        return p.has(key) ? p.get(key).getAsBigInteger().intValueExact() : fallback;
    }
    static Map<String,Object> method(MethodNode m,int index) {
        String id=m.getMethodInfo().getShortId(), raw=m.getMethodInfo().getName();
        return row("name",m.getAlias(),"overload_index",index,"raw_short_id",id,
            "raw_method_id",m.getMethodInfo().getRawFullId(),"dex_descriptor",id.substring(raw.length()),
            "signature",m.getAlias()+"("+m.getArgTypes().stream().map(Object::toString).collect(Collectors.joining(", "))+"): "+m.getReturnType(),
            "access_flags",m.getRawAccessFlags(),"synthetic",m.getAccessFlags().isSynthetic(),
            "native",m.getAccessFlags().isNative(),"abstract",m.getAccessFlags().isAbstract(),
            "dex_entry",m.getInputFileName(),"method_code_offset",m.getMethodCodeOffset());
    }
    static List<MethodNode> methods(JavaClass cls) {
        List<MethodNode> list=new ArrayList<>(cls.getClassNode().getMethods());
        list.sort(Comparator.comparing(MethodNode::getAlias));
        return list;
    }
    static List<Map<String,Object>> metadata(JavaClass cls) {
        Map<String,Integer> indices=new HashMap<>();
        List<Map<String,Object>> rows=new ArrayList<>();
        for(MethodNode m:methods(cls)) {
            int index=indices.getOrDefault(m.getAlias(),0);
            indices.put(m.getAlias(),index+1);
            rows.add(method(m,index));
        }
        return rows;
    }
    static JavaClass choose(List<JavaClass> classes,JsonObject p) {
        String name=text(p,"class_name","");
        List<JavaClass> matches=classes.stream().filter(c->c.getFullName().equals(name)).toList();
        if(matches.isEmpty()) throw new IllegalArgumentException("Class not found: "+name);
        if(matches.size()!=1) throw new IllegalArgumentException("Class name is ambiguous: "+name);
        return matches.get(0);
    }
    static MethodNode chooseMethod(JavaClass cls,JsonObject p) {
        String name=text(p,"method_name","");
        List<MethodNode> matches=methods(cls).stream().filter(m->m.getAlias().equals(name)).toList();
        if(matches.isEmpty()) throw new IllegalArgumentException("Method not found: "+name);
        if(matches.size()>1 && !p.has("overload_index")) throw new IllegalArgumentException("Select overload_index for overloaded method: "+name);
        int index=number(p,"overload_index",0);
        if(index<0 || index>=matches.size()) throw new IllegalArgumentException("overload_index outside method list");
        return matches.get(index);
    }
    static String smali(JavaClass cls,String shortId) {
        List<String> blocks=new ArrayList<>();
        StringBuilder current=null;
        boolean selected=false;
        for(String line:cls.getSmali().split("\\R",-1)) {
            String stripped=line.strip();
            if(stripped.startsWith(".method ")) {
                current=new StringBuilder();
                selected=stripped.endsWith(" "+shortId);
            }
            if(current!=null) current.append(line).append('\n');
            if(stripped.equals(".end method") && current!=null) {
                if(selected) blocks.add(current.toString());
                current=null;
            }
        }
        if(blocks.size()!=1) throw new IllegalStateException("No unique complete Smali body for "+shortId);
        return blocks.get(0);
    }
    static Map<String,Object> page(List<?> all,JsonObject p) {
        BigInteger size=BigInteger.valueOf(all.size());
        BigInteger offset=p.has("offset")?p.get("offset").getAsBigInteger():BigInteger.ZERO;
        int start=offset.min(size).intValueExact();
        int end=!p.has("limit") || p.get("limit").isJsonNull() ? all.size() : offset.add(p.get("limit").getAsBigInteger()).min(size).intValueExact();
        return row("rows",all.subList(start,end),"total",all.size(),"offset",offset,"returned",end-start,"has_more",end<all.size());
    }
    static Map<String,Object> node(JavaNode node) {
        Map<String,Object> result=row("kind",node instanceof JavaMethod?"method":node instanceof JavaClass?"class":"field",
            "name",node.getFullName(),"class_name",node instanceof JavaClass?node.getFullName():node.getDeclaringClass().getFullName());
        if(node instanceof JavaMethod m) {
            result.put("raw_method_id",m.getMethodNode().getMethodInfo().getRawFullId());
            result.put("dex_entry",m.getMethodNode().getInputFileName());
        }
        return result;
    }
    static Map<String,Object> invokes(MethodNode caller,MethodNode target) {
        List<Map<String,Object>> result=new ArrayList<>();
        Map<String,Object> observation=row("direct_dex_invokes",result,"raw_instruction_stream_available",caller.getCodeReader()!=null,
            "direct_invokes_exhaustive",false);
        if(caller.getCodeReader()==null) return observation;
        try {
            caller.getCodeReader().visitInstructions(insn->{
            insn.decode();
            if(insn.getIndexType()!=InsnIndexType.METHOD_REF || !insn.getOpcode().name().startsWith("INVOKE_")) return;
            var ref=insn.getIndexAsMethod();
            ref.load();
            if(!MethodInfo.fromRef(caller.root(),ref).getRawFullId().equals(target.getMethodInfo().getRawFullId())) return;
            result.add(row("dex_entry",caller.getInputFileName(),"source_raw_method_id",caller.getMethodInfo().getRawFullId(),
                "target_raw_method_id",target.getMethodInfo().getRawFullId(),"dex_code_unit_offset",insn.getOffset(),
                "dex_method_index",insn.getIndex(),"opcode",insn.getOpcode().name()));
            });
            observation.put("direct_invokes_exhaustive",true);
        } catch(Exception ex) {
            observation.put("direct_invokes_error",ex.getClass().getSimpleName()+": "+ex.getMessage());
        }
        return observation;
    }
    public static void main(String[] args) throws Exception {
        JsonObject request=JsonParser.parseString(Files.readString(Path.of(args[0]))).getAsJsonObject();
        JsonObject p=request.getAsJsonObject("parameters");
        String op=request.get("operation").getAsString();
        JadxArgs config=new JadxArgs();
        config.setInputFile(Path.of(request.get("path").getAsString()).toFile());
        config.setOutDir(Path.of(args[1]).getParent().resolve("jadx-work").toFile());
        config.setThreadsCount(1);
        config.setDeobfuscationOn(false);
        config.setSkipFilesSave(true);
        try(JadxDecompiler dex=new JadxDecompiler(config)) {
            dex.load();
            List<JavaClass> classes=new ArrayList<>(dex.getClassesWithInners());
            Map<String,Object> output=row("jadx_version",JadxDecompiler.getVersion(),"status","observed",
                "limitations",List.of("Static DEX references do not establish runtime calls, reflection targets, JNI resolution or behavioral equivalence.",
                "Java text is a decompiler reconstruction. Smali is a DEX representation, not the original Java source."));
            // Capture raw members before code generation may inline or hide synthetic members.
            if(op.equals("android.package")) {
                List<Map<String,Object>> resources=new ArrayList<>();
                String manifest=null;
                for(ResourceFile resource:dex.getResources()) {
                    resources.add(row("name",resource.getOriginalName(),"type",resource.getType().toString()));
                    if(resource.getOriginalName().endsWith("AndroidManifest.xml")) {
                        var content=resource.loadContent();
                        if(content!=null && content.getText()!=null) manifest=content.getText().getCodeStr();
                    }
                }
                output.put("manifest_xml",manifest);
                output.put("resources",resources);
                output.put("class_count",classes.size());
                output.put("top_level_class_count",dex.getClasses().size());
            } else if(op.equals("android.classes")) {
                boolean inners=p.has("include_inner") && p.get("include_inner").getAsBoolean();
                List<JavaClass> selected=inners?classes:dex.getClasses();
                String query=text(p,"query","");
                List<Map<String,Object>> rows=new ArrayList<>();
                for(JavaClass cls:selected) if(cls.getFullName().contains(query))
                    rows.add(row("name",cls.getFullName(),"raw_name",cls.getRawName(),"inner",cls.isInner()));
                output.put("classes",page(rows,p));
                output.put("case_sensitive",true);
                output.put("duplicate_names",rows.stream().collect(Collectors.groupingBy(r->r.get("name"),LinkedHashMap::new,Collectors.counting())).entrySet().stream().filter(e->e.getValue()>1).map(e->row("name",e.getKey(),"count",e.getValue())).toList());
            } else {
                JavaClass cls=choose(classes,p);
                List<Map<String,Object>> members=metadata(cls);
                output.put("class_name",cls.getFullName());
                if(op.equals("android.class")) {
                    output.put("methods",members);
                    output.put("fields",cls.getClassNode().getFields().stream().map(f->row("name",f.getAlias(),"type",f.getType().toString(),"access_flags",f.getAccessFlags().rawValue(),"synthetic",f.getAccessFlags().isSynthetic())).toList());
                    output.put("inner_classes",cls.getClassNode().getInnerClasses().stream().map(ClassNode::getFullName).toList());
                    if(p.has("include_code") && p.get("include_code").getAsBoolean()) {
                        output.put("code",cls.getCode());
                        output.put("representation","decompiled-java");
                    }
                } else if(op.equals("android.method")) {
                    MethodNode target=chooseMethod(cls,p);
                    String shortId=target.getMethodInfo().getShortId();
                    Map<String,Object> identity=members.stream().filter(r->r.get("raw_short_id").equals(shortId)).findFirst().orElseThrow();
                    output.put("method",identity);
                    String code=null,reason=null,representation="decompiled-java";
                    if(target.getAccessFlags().isNative() || target.getAccessFlags().isAbstract()) {
                        reason="declaration-without-dex-body";
                        representation="declaration";
                    } else {
                        try {
                            if(target.getMethodInfo().getName().equals("<clinit>")) reason="static-initializer-can-be-folded";
                            else {
                                code=target.getCodeStr();
                                if(code==null || code.isBlank()) reason="method-not-present-in-generated-java";
                            }
                        } catch(Exception ex) { reason=ex.getClass().getSimpleName()+": "+ex.getMessage(); }
                        if(reason!=null) { code=smali(cls,shortId); representation="smali"; }
                    }
                    output.put("code",code);
                    output.put("representation",representation);
                    output.put("fallback_reason",reason);
                    output.put("truncated",false);
                } else if(op.equals("android.references")) {
                    MethodNode target=p.has("method_name")?chooseMethod(cls,p):null;
                    dex.getRoot().runPreDecompileStage();
                    JavaNode selected=target==null?cls:dex.getJavaNodeByRef(target);
                    List<Map<String,Object>> uses=new ArrayList<>();
                    List<? extends JavaNode> incoming=target==null?cls.getUseIn():target.getUseIn().stream().map(dex::getJavaNodeByRef).toList();
                    for(JavaNode caller:incoming) {
                        Map<String,Object> observed=node(caller);
                        if(caller instanceof JavaMethod m && target!=null) {
                            observed.putAll(invokes(m.getMethodNode(),target));
                        }
                        if(p.has("resolve_lines") && p.get("resolve_lines").getAsBoolean()) {
                            try {
                            JavaClass owner=caller instanceof JavaClass c?c:caller.getDeclaringClass();
                            ICodeInfo info=owner.getTopParentClass().getCodeInfo();
                            List<Integer> offsets=owner.getTopParentClass().getUsePlacesFor(info,selected);
                            String code=info.getCodeStr();
                            observed.put("decompiled_positions",offsets.stream()
                                .filter(n->!(caller instanceof JavaMethod m) || info.getCodeMetadata().getNodeAt(n)==m.getMethodNode())
                                .map(n->row("utf16_offset",n,"line",1+code.substring(0,Math.min(n,code.length())).chars().filter(ch->ch=='\n').count())).toList());
                            observed.put("decompiled_source_class",owner.getTopParentClass().getFullName());
                            observed.put("position_scope",caller instanceof JavaMethod?"matched enclosing method metadata":"containing top-level class");
                            } catch(Exception ex) {
                                observed.put("position_resolution_error",ex.getClass().getSimpleName()+": "+ex.getMessage());
                            }
                        }
                        uses.add(observed);
                    }
                    output.put("target",target==null?node(cls):method(target,number(p,"overload_index",0)));
                    output.put("references",page(uses,p));
                    output.put("count_semantics","containing nodes, not invoke instructions");
                } else throw new IllegalArgumentException("Unknown Android operation: "+op);
            }
            output.put("diagnostics",row("errors",dex.getErrorsCount(),"warnings",dex.getWarnsCount()));
            Files.writeString(Path.of(args[1]),JSON.toJson(output));
        }
    }
}
