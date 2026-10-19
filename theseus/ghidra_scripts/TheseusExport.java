// Export mechanical function observations for the local inspection project.
// @category Theseus
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.framework.Application;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import com.google.gson.GsonBuilder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class TheseusExport extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 1) throw new IllegalArgumentException("Expected export file path");
        Map<String, Object> document = new LinkedHashMap<>();
        document.put("engine", "Ghidra " + Application.getApplicationVersion());
        document.put("program", currentProgram.getName());
        document.put("language", currentProgram.getLanguageID().toString());
        document.put("image_base", currentProgram.getImageBase().toString());
        document.put("certainty", "engine_inferred");
        List<Map<String, Object>> functions = new ArrayList<>();
        DecompInterface decompiler = new DecompInterface();
        if (!decompiler.openProgram(currentProgram)) throw new IllegalStateException(decompiler.getLastMessage());
        try {
            FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
            while (iterator.hasNext() && !monitor.isCancelled()) {
                Function function = iterator.next();
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("name", function.getName());
                row.put("address", function.getEntryPoint().toString());
                row.put("signature", function.getSignature().getPrototypeString());
                row.put("external", function.isExternal());
                row.put("thunk", function.isThunk());
                List<Map<String, String>> calls = new ArrayList<>();
                for (Function callee : function.getCalledFunctions(monitor)) {
                    Map<String, String> target = new LinkedHashMap<>();
                    target.put("name", callee.getName());
                    target.put("address", callee.getEntryPoint().toString());
                    calls.add(target);
                }
                row.put("calls", calls);
                if (!function.isExternal()) {
                    DecompileResults output = decompiler.decompileFunction(function, 0, monitor);
                    if (output != null && output.decompileCompleted()) {
                        row.put("code", output.getDecompiledFunction().getC());
                    } else {
                        row.put("error", output == null ? "No decompiler result" : output.getErrorMessage());
                    }
                }
                functions.add(row);
                println("THESEUS_FUNCTION " + functions.size() + " " + function.getName());
            }
        } finally {
            decompiler.dispose();
        }
        document.put("functions", functions);
        Files.writeString(Path.of(arguments[0]), new GsonBuilder().setPrettyPrinting().create().toJson(document), StandardCharsets.UTF_8);
    }
}
