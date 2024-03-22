import math
import torch
import warnings
import ml_collections
import random
import torch.nn.functional as F


def DiffAugment(x, types=[], prob=0.5, detach=True):
  """
  x.shape = B, C, H, W
  """
  if random.random() < prob:
    with torch.set_grad_enabled(not detach):
      x = random_hflip(x, prob=0.5)
      for p in types:
        for f in AUGMENT_FNS[p]:
          x = f(x)
      x = x.contiguous()
  return x


def random_hflip(tensor, prob):
  if prob > random.random():
    return tensor
  return torch.flip(tensor, dims=(3,))


def rand_brightness(x):
  x = x + (torch.rand(x.size(0), 1, 1, 1, dtype=x.dtype, device=x.device) - 0.5)
  return x


def rand_saturation(x):
  x_mean = x.mean(dim=1, keepdim=True)
  x = (x - x_mean) * (torch.rand(x.size(0), 1, 1, 1, dtype=x.dtype, device=x.device) * 2) + x_mean
  return x


def rand_contrast(x):
  x_mean = x.mean(dim=[1, 2, 3], keepdim=True)
  x = (x - x_mean) * (torch.rand(x.size(0), 1, 1, 1, dtype=x.dtype, device=x.device) + 0.5) + x_mean
  return x


def rand_translation(x, ratio=0.125):
  shift_x, shift_y = int(x.size(2) * ratio + 0.5), int(x.size(3) * ratio + 0.5)
  translation_x = torch.randint(-shift_x, shift_x + 1, size=[x.size(0), 1, 1], device=x.device)
  translation_y = torch.randint(-shift_y, shift_y + 1, size=[x.size(0), 1, 1], device=x.device)
  grid_batch, grid_x, grid_y = torch.meshgrid(
    torch.arange(x.size(0), dtype=torch.long, device=x.device),
    torch.arange(x.size(2), dtype=torch.long, device=x.device),
    torch.arange(x.size(3), dtype=torch.long, device=x.device),
  )
  grid_x = torch.clamp(grid_x + translation_x + 1, 0, x.size(2) + 1)
  grid_y = torch.clamp(grid_y + translation_y + 1, 0, x.size(3) + 1)
  x_pad = F.pad(x, [1, 1, 1, 1, 0, 0, 0, 0])
  x = x_pad.permute(0, 2, 3, 1).contiguous()[grid_batch, grid_x, grid_y].permute(0, 3, 1, 2)
  return x


def rand_offset(x, ratio=1, ratio_h=1, ratio_v=1):
  w, h = x.size(2), x.size(3)

  imgs = []
  for img in x.unbind(dim=0):
    max_h = int(w * ratio * ratio_h)
    max_v = int(h * ratio * ratio_v)

    value_h = random.randint(0, max_h) * 2 - max_h
    value_v = random.randint(0, max_v) * 2 - max_v

    if abs(value_h) > 0:
      img = torch.roll(img, value_h, 2)

    if abs(value_v) > 0:
      img = torch.roll(img, value_v, 1)

    imgs.append(img)

  return torch.stack(imgs)


def rand_offset_h(x, ratio=1):
  return rand_offset(x, ratio=1, ratio_h=ratio, ratio_v=0)


def rand_offset_v(x, ratio=1):
  return rand_offset(x, ratio=1, ratio_h=0, ratio_v=ratio)


def rand_cutout(x, ratio=0.5):
  cutout_size = int(x.size(2) * ratio + 0.5), int(x.size(3) * ratio + 0.5)
  offset_x = torch.randint(0, x.size(2) + (1 - cutout_size[0] % 2), size=[x.size(0), 1, 1], device=x.device)
  offset_y = torch.randint(0, x.size(3) + (1 - cutout_size[1] % 2), size=[x.size(0), 1, 1], device=x.device)
  grid_batch, grid_x, grid_y = torch.meshgrid(
    torch.arange(x.size(0), dtype=torch.long, device=x.device),
    torch.arange(cutout_size[0], dtype=torch.long, device=x.device),
    torch.arange(cutout_size[1], dtype=torch.long, device=x.device),
  )
  grid_x = torch.clamp(grid_x + offset_x - cutout_size[0] // 2, min=0, max=x.size(2) - 1)
  grid_y = torch.clamp(grid_y + offset_y - cutout_size[1] // 2, min=0, max=x.size(3) - 1)
  mask = torch.ones(x.size(0), x.size(2), x.size(3), dtype=x.dtype, device=x.device)
  mask[grid_batch, grid_x, grid_y] = 0
  x = x * mask.unsqueeze(1)
  return x


AUGMENT_FNS = {
  'color': [rand_brightness, rand_saturation, rand_contrast],
  'offset': [rand_offset],
  'offset_h': [rand_offset_h],
  'offset_v': [rand_offset_v],
  'translation': [rand_translation],
  'cutout': [rand_cutout],
}


def _no_grad_trunc_normal_(tensor, mean, std, a, b):
  # Cut & paste from PyTorch official master until it's in a few official releases - RW
  # Method based on https://people.sc.fsu.edu/~jburkardt/presentations/truncated_normal.pdf
  def norm_cdf(x):
    # Computes standard normal cumulative distribution function
    return (1. + math.erf(x / math.sqrt(2.))) / 2.

  if (mean < a - 2 * std) or (mean > b + 2 * std):
    warnings.warn("mean is more than 2 std from [a, b] in nn.init.trunc_normal_. "
                  "The distribution of values may be incorrect.",
                  stacklevel=2)

  with torch.no_grad():
    # Values are generated by using a truncated uniform distribution and
    # then using the inverse CDF for the normal distribution.
    # Get upper and lower cdf values
    l = norm_cdf((a - mean) / std)
    u = norm_cdf((b - mean) / std)

    # Uniformly fill tensor with values from [l, u], then translate to
    # [2l-1, 2u-1].
    tensor.uniform_(2 * l - 1, 2 * u - 1)

    # Use inverse cdf transform for normal distribution to get truncated
    # standard normal
    tensor.erfinv_()

    # Transform to proper mean, std
    tensor.mul_(std * math.sqrt(2.))
    tensor.add_(mean)

    # Clamp to ensure it's in the proper range
    tensor.clamp_(min=a, max=b)
    return tensor


def trunc_normal_(tensor, mean=0., std=1., a=-2., b=2.):
  # type: (Tensor, float, float, float, float) -> Tensor
  return _no_grad_trunc_normal_(tensor, mean, std, a, b)


def get_testing():
  """Returns a minimal configuration for testing."""
  config = ml_collections.ConfigDict()
  config.patches = ml_collections.ConfigDict({'size': (16, 16)})
  config.hidden_size = 1
  config.transformer = ml_collections.ConfigDict()
  config.transformer.mlp_dim = 1
  config.transformer.num_heads = 1
  config.transformer.num_layers = 1
  config.transformer.attention_dropout_rate = 0.0
  config.transformer.dropout_rate = 0.1
  config.classifier = 'token'
  config.representation_size = None
  return config


def get_b16_config():
  """Returns the ViT-B/16 configuration."""
  config = ml_collections.ConfigDict()
  config.patches = ml_collections.ConfigDict({'size': (16, 16)})
  config.hidden_size = 768
  config.transformer = ml_collections.ConfigDict()
  config.transformer.mlp_dim = 3072
  config.transformer.num_heads = 12
  config.transformer.num_layers = 12
  config.transformer.attention_dropout_rate = 0.0
  config.transformer.dropout_rate = 0.1
  config.classifier = 'token'
  config.representation_size = None
  return config


def get_r50_b16_config():
  """Returns the Resnet50 + ViT-B/16 configuration."""
  config = get_b16_config()
  del config.patches.size
  config.patches.grid = (14, 14)
  config.resnet = ml_collections.ConfigDict()
  config.resnet.num_layers = (3, 4, 9)
  config.resnet.width_factor = 1
  return config


def get_b32_config():
  """Returns the ViT-B/32 configuration."""
  config = get_b16_config()
  config.patches.size = (32, 32)
  return config


def get_l16_config():
  """Returns the ViT-L/16 configuration."""
  config = ml_collections.ConfigDict()
  config.patches = ml_collections.ConfigDict({'size': (16, 16)})
  config.hidden_size = 1024
  config.transformer = ml_collections.ConfigDict()
  config.transformer.mlp_dim = 4096
  config.transformer.num_heads = 16
  config.transformer.num_layers = 24
  config.transformer.attention_dropout_rate = 0.0
  config.transformer.dropout_rate = 0.1
  config.classifier = 'token'
  config.representation_size = None
  return config


def get_l32_config():
  """Returns the ViT-L/32 configuration."""
  config = get_l16_config()
  config.patches.size = (32, 32)
  return config


def get_h14_config():
  """Returns the ViT-L/16 configuration."""
  config = ml_collections.ConfigDict()
  config.patches = ml_collections.ConfigDict({'size': (14, 14)})
  config.hidden_size = 1280
  config.transformer = ml_collections.ConfigDict()
  config.transformer.mlp_dim = 5120
  config.transformer.num_heads = 16
  config.transformer.num_layers = 32
  config.transformer.attention_dropout_rate = 0.0
  config.transformer.dropout_rate = 0.1
  config.classifier = 'token'
  config.representation_size = None
  return config
