import numpy as np
import sys
import onnx
from onnx import numpy_helper
from NNet.utils.writeNNet import writeNNet
import copy
        
def onnx2nnet(onnxFile, inputMins=None, inputMaxes=None, means=None, ranges=None, nnetFile="", inputName="", outputName="", take_transpose=False):
    '''
    Write a .nnet file from an onnx file
    Args:
        onnxFile: (string) Path to onnx file
        inputMins: (list) optional, Minimum values for each neural network input.
        inputMaxes: (list) optional, Maximum values for each neural network output.
        means: (list) optional, Mean value for each input and value for mean of all outputs, used for normalization
        ranges: (list) optional, Range value for each input and value for range of all outputs, used for normalization
        inputName: (string) optional, Name of operation corresponding to input.
        outputName: (string) optional, Name of operation corresponding to output.
        take_transpose: (Bool) optional, determines whether to take transpose of weights
    '''
    
    if nnetFile=="":
        nnetFile = onnxFile[:-4] + 'nnet'

    model = onnx.load(onnxFile)
    graph = model.graph
    
    if not inputName:
        assert len(graph.input)==1
        inputName = graph.input[0].name
    if not outputName:
        assert len(graph.output)==1
        outputName = graph.output[0].name
    
    # Search through nodes until we find the inputName.
    # Accumulate the weight matrices and bias vectors into lists.
    # Continue through the network until we reach outputName.
    # This assumes that the network is "frozen", and the model uses initializers to set weight and bias array values.
    weights = []
    biases = []
    
    # Loop through nodes in graph
    for node in graph.node:
        
        # Ignore nodes that do not use inputName as an input to the node
        if inputName in node.input:
            
            # This supports three types of nodes: MatMul, Add, and Relu
            # The .nnet file format specifies only feedforward fully-connected Relu networks, so
            # these operations are sufficient to specify nnet networks. If the onnx model uses other 
            # operations, this will break.
            if node.op_type=="MatMul":
                assert len(node.input)==2
                
                # Find the name of the weight matrix, which should be the other input to the node
                weightIndex=0
                if node.input[0]==inputName:
                    weightIndex=1
                weightName = node.input[weightIndex]
                
                # Extract the value of the weight matrix from the initializers
                weights+= [numpy_helper.to_array(inits) for inits in graph.initializer if inits.name==weightName]
                
                # Update inputName to be the output of this node
                inputName = node.output[0]
                
            elif node.op_type=="Add":
                assert len(node.input)==2
                
                # Find the name of the bias vector, which should be the other input to the node
                biasIndex=0
                if node.input[0]==inputName:
                    biasIndex=1
                biasName = node.input[biasIndex]
                
                # Extract the value of the bias vector from the initializers
                biases+= [numpy_helper.to_array(inits) for inits in graph.initializer if inits.name==biasName]
                
                # Update inputName to be the output of this node
                inputName = node.output[0]
            
            elif node.op_type=="Gemm":
                assert len(node.input) == 3
                # check attributes for transpose
                alpha = 1.0
                beta = 1.0
                transA = False
                transB = False
                for attr in node.attribute:
                    if attr.name == "alpha":
                        alpha = attr.f
                    elif attr.name == "beta":
                        beta = attr.f
                    elif attr.name == "transA":
                        transA = bool(attr.i)
                    elif attr.name == "transB":
                        transB = bool(attr.i)
                        # honestly not sure what to do with this because the input has to have shape (n_features X batch_size)
                # first node input is name of node
                weightName = node.input[1]
                biasName = node.input[2]
                # get weights
                weight = copy.deepcopy([numpy_helper.to_array(inits) for inits in graph.initializer if inits.name==weightName][0])
                if transA:
                    weight = weight.transpose()
                weight *= alpha 
                weights += [weight]
                # get bias
                if biasName in [i.name for i in graph.initializer]:
                    bias = copy.deepcopy([numpy_helper.to_array(inits) for inits in graph.initializer if inits.name==biasName][0])
                else: # bias is zeros 
                    bias = np.zeros(weight.shape[0])
                bias *= beta 
                biases += [bias]

                # Update inputName to be the output of this node
                inputName = node.output[0]

            # For the .nnet file format, the Relu's are implicit, so we just need to update the input
            elif node.op_type=="Relu":
                inputName = node.output[0]
                
            # If there is a different node in the model that is not supported, through an error and break out of the loop
            else:
                print("Node operation type %s not supported!"%node.op_type)
                weights = []
                biases=[]
                break
                
            # Terminate once we find the outputName in the graph
            if outputName == inputName:
                break
    
    if take_transpose:
        # necessary for older networks that don't use Gemm
        print("taking transpose of weights...")
        weights = [np.transpose(w) for w in weights]

    # Check if the weights and biases were extracted correctly from the graph
    if outputName==inputName and len(weights)>0 and len(weights)==len(biases):
        
        inputSize = weights[0].shape[0]
        
        # Default values for input bounds and normalization constants
        if inputMins is None: inputMins = inputSize*[np.finfo(np.float32).min]
        if inputMaxes is None: inputMaxes = inputSize*[np.finfo(np.float32).max]
        if means is None: means = (inputSize+1)*[0.0]
        if ranges is None: ranges = (inputSize+1)*[1.0]
            
        # Print statements
        print("Converted ONNX model at %s"%onnxFile)
        print("    to an NNet model at %s"%nnetFile)

        print("inputMins:", inputMins)
        print("inputMaxes:", inputMaxes)
        
        # Write NNet file
        writeNNet(weights,biases,inputMins,inputMaxes,means,ranges,nnetFile)
        
    # Something went wrong, so don't write the NNet file
    else:
        if not outputName==inputName:
            print("outputName!=inputName, outputName=", outputName, ", inputName=", inputName)
        if not len(weights) > 0:
            print("len(weights)= ",len(weights))
        if not len(weights)==len(biases):
            print("len(weights)!=len(biases), len(weights)= ", len(weights), ", len(biases)= ", len(biases))
        print("Could not write NNet file!")
        
if __name__ == '__main__':
    # Read user inputs and run onnx2nnet function
    # If non-default values of input bounds and normalization constants are needed, 
    # this function should be run from a script instead of the command line
    if len(sys.argv)>1:
        print("WARNING: Using the default values of input bounds and normalization constants")
        onnxFile = sys.argv[1]
        if len(sys.argv)>2:
            nnetFile = sys.argv[2]
            onnx2nnet(onnxFile,nnetFile=nnetFile)
        else: onnx2nnet(onnxFile)
    else:
        print("Need to specify which ONNX file to convert to .nnet!")
