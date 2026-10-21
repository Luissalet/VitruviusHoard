/** Native inventory and application projections over directly incorporated readers. */
import {basename,dirname,join,relative,sep} from 'node:path';
import {stat} from 'node:fs/promises';
import {z} from 'zod';
import {ArtifactResourceScope} from './src/artifacts/ArtifactResourceScope.js';
import {inventoryArtifact} from './src/artifacts/inventory/ArtifactInventory.js';
import {extractArtifact} from './src/artifacts/extraction/ArtifactExtraction.js';
import {createEvidence} from './src/domain/evidence.js';
import {projectAppleApplication} from './src/domain/apple/appleApplication.js';
import {projectAndroidApplication} from './src/domain/android/androidApplication.js';
import {projectHarmonyApplication} from './src/domain/harmony/harmonyApplication.js';
import {analyzeInterfaceBuilderBundle} from './src/artifacts/apple/InterfaceBuilderAnalysis.js';
import {analyzeAppleAssetCatalogs} from './src/artifacts/apple/AppleAssetCatalogAnalysis.js';
import {traceDylibResolution} from './src/artifacts/apple/DylibResolutionReader.js';
import {inspectManagedArtifactBytes} from './src/dotnet/ManagedArtifactInspector.js';
import {inspectManagedMembersBytes} from './src/dotnet/ManagedMemberInspector.js';
import {inspectManagedNativeBoundariesBytes} from './src/dotnet/ManagedNativeBoundaryInspector.js';
import {projectManagedApplicationGraph} from './src/domain/managed/managedApplicationGraph.js';
import {readManagedPeLayout} from './src/dotnet/ManagedPeReader.js';
import type {BinaryTarget} from './src/domain/binaryTargetTypes.js';
import type {JsonValue} from './src/domain/jsonValue.js';

const provider={id:'theseus-static',name:'Theseus static application analysis',version:'1'};

const BUNDLE_SUFFIXES=['.app','.framework','.bundle','.appex','.xpc','.plugin'];

const exists=async(path:string):Promise<boolean>=>{
  try {await stat(path);return true;} catch {return false;}
};

/** A folder is a bundle when it has a bundle name and the Info.plist of a macOS, iOS or framework layout. */
const isBundle=async(folder:string):Promise<boolean>=>
  BUNDLE_SUFFIXES.some(suffix=>basename(folder).toLowerCase().endsWith(suffix)) &&
  (await exists(join(folder,'Contents','Info.plist')) || await exists(join(folder,'Info.plist')) ||
   await exists(join(folder,'Resources','Info.plist')) || await exists(join(folder,'Versions','Current','Resources','Info.plist')));

/**
 * The enclosing bundles of an image, innermost first. The chain stops at the first folder that carries a
 * bundle name without being a bundle, so a plain folder named like one never widens what is read.
 */
const enclosingBundles=async(path:string):Promise<string[]>=>{
  const chain:string[]=[];
  for(let folder=dirname(path);dirname(folder)!==folder;folder=dirname(folder)) {
    if(!BUNDLE_SUFFIXES.some(suffix=>basename(folder).toLowerCase().endsWith(suffix))) continue;
    if(!(await isBundle(folder))) break;
    chain.push(folder);
  }
  return chain;
};

export async function analyzePortfolio(operation:string,bytes:Buffer,path:string,sha256:string,
  parameters:{output_directory?:string|undefined;query?:unknown}):Promise<unknown> {
  const resources=new ArtifactResourceScope();
  try {
    if(operation==='managed.graph') {
      const layout=readManagedPeLayout(bytes);
      const target:BinaryTarget={path,sha256,kind:'executable',format:'pe',architecture:layout.architecture,
        availableArchitectures:[layout.architecture],peMachine:layout.machine,managed:layout.cliDirectoryState!=='absent',
        executableRole:(layout.characteristics&0x2000)?'shared-library':'application'};
      const evidence=(name:string,result:unknown)=>createEvidence(target,provider,{operation:name,parameters:{},
        result:result as JsonValue,rawResult:null,confidence:'observed',authority:'shipped-artifact'});
      return projectManagedApplicationGraph({
        managed_artifact:evidence('inspect_managed_artifact',inspectManagedArtifactBytes(bytes,target)),
        managed_members:evidence('inspect_managed_members',inspectManagedMembersBytes(bytes,target,{})),
        managed_native_boundaries:evidence('inspect_managed_native_boundaries',inspectManagedNativeBoundariesBytes(bytes,target))});
    }
    if(operation==='apple.interface_builder') return await analyzeInterfaceBuilderBundle({bundlePath:path,targetSha256:sha256,limits:parameters.query});
    if(operation==='apple.assets') return await analyzeAppleAssetCatalogs({bundlePath:path,targetSha256:sha256,environment:process.env,page:parameters.query});
    if(operation==='apple.dylibs') {
      // A selected folder is the analyzed root and every executable in it is traced. A selected image is
      // traced inside its outermost enclosing bundle by default (root_scope 'enclosing-bundle'), so
      // @executable_path/../Frameworks stays inside the root; root_scope 'image-folder' keeps its own folder.
      const {root_scope:scope='enclosing-bundle',...query}=z.object({root_scope:z.enum(['enclosing-bundle','image-folder']).optional()})
        .passthrough().parse(parameters.query??{});
      const directory=(await stat(path)).isDirectory();
      const bundles=directory || scope==='image-folder' ? [] : await enclosingBundles(path);
      const rootPath=directory ? path : bundles.at(-1) ?? dirname(path);
      const rule=directory ? 'selected-folder' : bundles.length ? 'enclosing-bundle' : 'image-folder';
      const result=await traceDylibResolution({rootPath,targetPath:path,targetSha256:sha256,enumerateRoots:directory,
        parameters:query,resourceScope:resources});
      const portable=(folder:string)=>relative(rootPath,folder).split(sep).join('/');
      return {...result,root_selection:{rule,requested_scope:directory ? null : scope,
        selected:directory ? '' : portable(path),bundles:bundles.map(portable),
        // Images other than the selected one were read because dyld would load them from inside this root.
        read_beyond_selection:directory ? [] : result.images.map(image=>image.path).filter(image=>image!==portable(path))}};
    }
    const inventory=await inventoryArtifact(path,{resourceScope:resources,environment:process.env,integrity:{mode:'record-and-continue'}});
    if(operation==='artifact.inventory') return inventory;
    if(operation==='artifact.extract') {
      if(!parameters.output_directory) throw new Error('An extraction output directory is required');
      return await extractArtifact({inputPath:path,inputFormat:inventory.manifest.root_format,outputRoot:parameters.output_directory,
        environment:process.env,integrityPolicy:'record-and-continue',resourceScope:resources});
    }
    const carrier=createEvidence({path,sha256:inventory.manifest.root_sha256,format:inventory.manifest.root_format},provider,
      {operation:'inventory_artifact',parameters:{},result:inventory as unknown as JsonValue,rawResult:null,
       confidence:'observed',authority:'shipped-artifact',limitations:inventory.limitations});
    const input={inventory_evidence:[carrier]};
    if(operation==='apple.application') return projectAppleApplication(input);
    if(operation==='android.application') return projectAndroidApplication(input);
    if(operation==='harmony.application') return projectHarmonyApplication(input);
    throw new Error('Unknown portfolio operation: '+operation);
  } finally {await resources.close();}
}
