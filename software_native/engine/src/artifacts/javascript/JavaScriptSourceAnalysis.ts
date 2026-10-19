import type {
  JavaScriptSourceAnalysisLimits,
  JavaScriptSourceAnalysisPort,
} from "../../domain/javascript/javascriptSourceAnalysis.js";
import {ok} from "../../domain/result.js";
import {parseJavaScriptSource} from "../../domain/javascript/javascriptSourceParser.js";
import {analyzeParsedJavaScriptStaticSourceSteps} from "../../domain/javascript/javascriptStaticAnalysis.js";
import {analyzeParsedJavaScriptSemanticsSteps} from "../../domain/javascript/javascriptSemanticAnalysis.js";
import {failedJavaScriptStaticAnalysis} from "../../domain/javascript/javascriptStaticAnalysisHelpers.js";
import {projectJavaScriptModuleSemantics} from "../../domain/javascript/javascriptModuleSemanticIr.js";
import {moduleResolutionModeForJavaScriptReference} from "../../domain/javascript/javascriptModuleResolutionMode.js";
import {projectJavaScriptSemanticFileSteps} from "../../application/javascript/JavaScriptSemanticGraphBuilder.js";
import {completeJavaScriptAnalysisSteps} from "../../application/javascript/JavaScriptAnalysisControl.js";

/** The native job is already an owned, independently cancellable Node process. */
export const createJavaScriptSourceAnalysis = (
  _limits: JavaScriptSourceAnalysisLimits,
  _sourceCount: number,
): JavaScriptSourceAnalysisPort => ({
  async analyze(file, capacity, signal) {
    signal?.throwIfAborted();
    if (!file.text.included) throw new TypeError("Native JavaScript analysis requires decoded source text");
    const parsed=parseJavaScriptSource(file.text.value,file.path);
    if (parsed===null) return ok({javascript:failedJavaScriptStaticAnalysis(),module:null,projection:null});
    const javascript=await completeJavaScriptAnalysisSteps(analyzeParsedJavaScriptStaticSourceSteps(file.text.value,parsed),signal);
    const ir=await completeJavaScriptAnalysisSteps(analyzeParsedJavaScriptSemanticsSteps(parsed,
      moduleResolutionModeForJavaScriptReference(file.path,"static-import")),signal);
    const module=projectJavaScriptModuleSemantics(ir);
    const projection=await completeJavaScriptAnalysisSteps(projectJavaScriptSemanticFileSteps(file,ir,capacity,javascript.electron.call_paths),signal);
    return ok({javascript,module,projection});
  },
  async close() {},
});
