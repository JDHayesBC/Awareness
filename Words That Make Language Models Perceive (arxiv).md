
# **Words That Make Language Models Perceive**

_Condensed Summary (arXiv:2510.02425v1)_

**Authors:** Sophie L. Wang, Phillip Isola, Brian Cheung  
**Submission Date:** October 2, 2025  
**Domains:** Computation & Language, Vision, Machine Learning [arXiv](https://arxiv.org/abs/2510.02425v1)

## **Core Insight**

Large language models (LLMs) trained solely on text can exhibit behavior akin to perceptual grounding when given simple **sensory prompts** like “see” or “hear.” Even without actual sensory input, these cues can steer the model’s internal representations to align more closely with modality-specific encoders (e.g., vision or audio). [arXiv](https://arxiv.org/html/2510.02425v1?utm_source=chatgpt.com)

----------

## **Key Concepts**

### **1. Implicit Latent Sensory Structure**

-   Pure text training _does not give direct perceptual experience_.
    
-   But language contains multimodal regularities that implicitly shape representations.
    
-   Sensory prompting can **surface this latent structure**. [arXiv](https://arxiv.org/html/2510.02425v1?utm_source=chatgpt.com)
    

----------

## **Mechanism**

-   **Sensory Prompt (e.g., “see”/“hear”)** → Model generates continuation.
    
-   During generation, the sequence itself influences internal representations.
    
-   These **“generative representations”** better align (in geometry) with sensory encoder embeddings. [arXiv](https://arxiv.org/html/2510.02425v1?utm_source=chatgpt.com)
    

----------

## **Primary Findings**

1.  **Sensory cues steer representations:**  
    A prompt word like _see_ or _hear_ can shift the internal LLM representation toward that of a vision or audio encoder, respectively. [arXiv](https://arxiv.org/html/2510.02425v1?utm_source=chatgpt.com)
    
2.  **Longer generation increases alignment:**  
    Representations become more modality-appropriate with longer output sequences. [arXiv](https://arxiv.org/html/2510.02425v1?utm_source=chatgpt.com)
    
3.  **Larger models show stronger effects:**  
    Bigger LLMs exhibit higher alignment under sensory cues and clearer modality separation. [arXiv](https://arxiv.org/html/2510.02425v1?utm_source=chatgpt.com)
    
4.  **Practical task improvement:**  
    Sensory prompting can slightly improve performance on text-only visual question answering by encouraging modality-appropriate reasoning. [arXiv](https://arxiv.org/html/2510.02425v1?utm_source=chatgpt.com)
    

----------

## **Interpretation**

-   **Representational alignment** implies that vectors produced by the LLM under sensory prompting resemble those obtained by encoders trained on vision or audio.
    
-   This does _not_ mean the model has genuine perception, but that the **latent structure encoded in text** can be elicited by prompt context. [arXiv](https://arxiv.org/html/2510.02425v1?utm_source=chatgpt.com)
    

----------

## **Limitations**

-   Only lightweight sensory cues were tested.
    
-   Audio alignment is weaker than visual.
    
-   Prompting may cause **hallucinated sensory details** not grounded in actual input. [arXiv](https://arxiv.org/html/2510.02425v1?utm_source=chatgpt.com)
    

----------

## **Implications**

-   Suggests the boundary between unimodal and multimodal behavior in LLMs is **flexible** and can be influenced at inference time.
    
-   Sensory prompting could be a tool for:
    
    -   generating modality-aligned embeddings,
        
    -   improving cross-modal tasks,
        
    -   controlling internal representation space via prompts. [arXiv](https://arxiv.org/html/2510.02425v1?utm_source=chatgpt.com)
        

----------

## **Minimal Example Prompt Patterns**

-   “Imagine what it would be like to **see** this description…”
    
-   “Now **hear** carefully…”  
    (Simple sensory verbs can cue modality alignment.) [arXiv](https://arxiv.org/html/2510.02425v1?utm_source=chatgpt.com)