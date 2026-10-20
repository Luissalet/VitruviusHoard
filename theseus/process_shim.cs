// First-party scenario command: preserve the CLR argv and binary standard streams.
using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;

[DataContract]
class Invocation {
    [DataMember] public string name;
    [DataMember] public string[] argv;
    [DataMember] public string cwd;
    [DataMember] public string stdin_base64;
}
[DataContract]
class Reply {
    [DataMember] public string stdout_base64;
    [DataMember] public string stderr_base64;
    [DataMember] public int exit_code;
}
class ScenarioCommand {
    static int Main(string[] argv) {
        try {
            string name=Path.GetFileNameWithoutExtension(Process.GetCurrentProcess().MainModule.FileName);
            byte[] input;
            using(var buffer=new MemoryStream()) {
                Console.OpenStandardInput().CopyTo(buffer);input=buffer.ToArray();
            }
            var invocation=new Invocation {name=name,argv=argv,cwd=Environment.CurrentDirectory,stdin_base64=Convert.ToBase64String(input)};
            var request=(HttpWebRequest)WebRequest.Create(Environment.GetEnvironmentVariable("VITRUVIUS_CAPTURE_COMMAND_URL")+"/"+Uri.EscapeDataString(name));
            request.Proxy=null;request.Method="POST";request.ContentType="application/json";
            request.Timeout=System.Threading.Timeout.Infinite;request.ReadWriteTimeout=System.Threading.Timeout.Infinite;
            using(var buffer=new MemoryStream()) {
                new DataContractJsonSerializer(typeof(Invocation)).WriteObject(buffer,invocation);
                request.ContentLength=buffer.Length;
                using(var stream=request.GetRequestStream())buffer.WriteTo(stream);
            }
            Reply reply;
            using(var response=request.GetResponse())using(var stream=response.GetResponseStream())
                reply=(Reply)new DataContractJsonSerializer(typeof(Reply)).ReadObject(stream);
            byte[] stdout=Convert.FromBase64String(reply.stdout_base64),stderr=Convert.FromBase64String(reply.stderr_base64);
            var output=Console.OpenStandardOutput();output.Write(stdout,0,stdout.Length);output.Flush();
            var errors=Console.OpenStandardError();errors.Write(stderr,0,stderr.Length);errors.Flush();
            return reply.exit_code;
        } catch(Exception error) {
            Console.Error.WriteLine("Scenario command observation failed: "+error.Message);return 125;
        }
    }
}
