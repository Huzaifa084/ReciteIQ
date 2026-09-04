"""Direct FastConformer inference: preprocess -> encoder -> RNN-T decode,
bypassing transcribe()'s per-call manifest + dataloader construction."""
import numpy as np, torch

def prepare(model):
    """Inference-time featurizer settings. transcribe() sets these internally;
    dither injects noise, so leaving it on would make output non-deterministic."""
    model.preprocessor.featurizer.dither = 0.0
    model.preprocessor.featurizer.pad_to = 0
    model.eval()
    return model

@torch.no_grad()
def transcribe_direct(model, audio: np.ndarray) -> str:
    sig = torch.as_tensor(audio, dtype=torch.float32).unsqueeze(0)
    ln = torch.tensor([sig.shape[1]], dtype=torch.long)
    proc, proc_len = model.preprocessor(input_signal=sig, length=ln)
    enc, enc_len = model.encoder(audio_signal=proc, length=proc_len)
    hyps = model.decoding.rnnt_decoder_predictions_tensor(enc, enc_len, return_hypotheses=False)
    h = hyps[0]
    return h.text if hasattr(h, "text") else str(h)
