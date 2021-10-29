import os,sys
import numpy as np
import urllib.request
import tarfile
from keras.models import model_from_json
import mbircone
import demo_utils, denoiser_utils
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2' 

"""
This file demonstrates the usage of mace3D reconstruction algorithm by downloading phantom and denoiser data from a url, generating sinogram by projecting the phantom and adding transmission noise, and finally performing a 3D MACE reconstruction.
"""
print('This file demonstrates the usage of mace3D reconstruction algorithm by downloading phantom and denoiser data from a url, generating sinogram by projecting the phantom, and finally performing a 3D MACE reconstruction.\n')


################ Define Parameters
########## Geometry parameters
dist_source_detector = 839.0472 # Distance between the X-ray source and the detector in units of ALU
magnification = 5.572128439964856 # magnification is defined as (source to detector distance)/(source to center-of-rotation distance)
delta_pixel_detector = 0.25 # Scalar value of detector pixel spacing in units of ALU
num_det_rows = 28 # number of detector rows
num_det_channels = 240 # number of detector channels

########## Simulated sinogram parameters
num_views = 75 # number of projection views
sino_noise_sigma = 0.01 # transmission noise level
########## Download url and extract path.
download_url = 'https://github.com/dyang37/mbircone_data/raw/master/demo_data.tar.gz' # url to download the demo data
extract_path = './demo_data/' # destination path to extract the downloaded tarball file
# path to downloaded files. Please change them accordingly if you replace any of them with your own files.
phantom_path = os.path.join(extract_path, 'phantom_3D.npy') # 3D image volume phantom file
data_param_path = os.path.join(extract_path, './dncnn_params/')# pre-trained dncnn model parameter files
output_dir = './output/mace3D/' # path to store output recon images

########## MACE recon parameters
max_admm_itr = 10 # max ADMM iterations for MACE reconstruction
prior_weight = 0.5 # cumulative weights for three prior agents.
denoiser_type = 'dncnn_ct' # Denoiser function to be used in MACE. Should be one of dncnn_vanila or dncnn_ct


################ Download and extract data
"""
Download phantom and cnn denoiser params files.
# A tarball file will be downloaded from the given url and extracted to extract_path.
# The tarball file downloaded from the default url in this demo contains the following files:
# an image volume phantom file phantom_3D.npy. You can replace this file with your own phantom data.
# dncnn parameter files stored in dncnn_params/ directory
"""
demo_utils.download_and_extract(download_url, extract_path)


################ Generate sinogram
print("Generating sinogram ...")
# Generate array of view angles
angles = np.linspace(0, 2*np.pi, num_views, endpoint=False)
# Generate clean sinogram by projecting phantom
phantom = np.load(phantom_path)
sino = mbircone.cone3D.project(phantom,angles,
            num_det_rows, num_det_channels,
            dist_source_detector, magnification,
            delta_pixel_detector=delta_pixel_detector)
# Calculate sinogram weights
weights = mbircone.cone3D.calc_weights(sino, weight_type='transmission')
# Add transmission noise to clean sinogram
noise = sino_noise_sigma * 1./np.sqrt(weights) * np.random.normal(size=(num_views,num_det_rows,num_det_channels))
sino_noisy = sino + noise


# two example denoiser functions used in this MACE demo
# denoiser function for DnCNN model trained with keras on natural images
def dncnn_denoiser_vanila(img_noisy, denoiser_model):
    """ This is an example of a cnn denoiser function. This denoiser works with either 3D or 4D image batch.

        Args:
            img_noisy (ndarray): noisy image batch with shape (Nz,N0,N1,...,Nm).
            denoiser_model (class object): A pre-trained cnn denoiser model object.
        Returns:
            ndarray: denoised image batch with shape (Nz,N0,N1,...,Nm).
    """
    img_noisy = img_noisy[..., np.newaxis] # (Nz,N0,N1,...,Nm,1)
    img_denoised = denoiser_model.predict(img_noisy) # inference
    return np.squeeze(img_denoised)


# denoiser function for DnCNN model trained with tensorflow on CT images
def dncnn_denoiser_ct(img_noisy, denoiser_model):
    ''' This is an example of a Tensorflow denoiser. This denoiser works with either 3D or 4D image batch.

        Args:
            img_noisy (ndarray): noisy image batch with shape (Nz,N0,N1,... ,Nm).
            denoiser_model (Tensorflow instance): A pre-trained tensorflow denoiser model.
        Returns:
            ndarray: denoised image batch with shape (Nz,N0,N1,...,Nm).
    '''
    # expand the input image volume to the shape of (Nz,1,N0,N1,...,Nm)
    img_noisy = np.expand_dims(img_noisy, axis=1)
    testData_obj = denoiser_utils.DataLoader(img_noisy)
    denoiser_model.test(testData_obj)
    img_denoised = np.stack(testData_obj.outData, axis=0)
    return np.squeeze(img_denoised)


################ Load denoiser function and model according to given denoiser type
print("Loading denoiser function and model ...")
if denoiser_type == "dncnn_vanila":
    print("Denoiser function: use DnCNN trained on natural images.")
    # use dncnn_denoiser_vanila function as input to MACE
    denoiser_func = dncnn_denoiser_vanila
    # Load denoiser model structure and weights
    json_path = os.path.join(data_param_path, 'model_dncnn/model.json') # model architecture file
    weight_path = os.path.join(data_param_path, 'model_dncnn/model.hdf5') # model weight file
    json_file = open(json_path, 'r')
    denoiser_model_json = json_file.read() # load model architecture
    json_file.close()
    denoiser_model = model_from_json(denoiser_model_json)
    denoiser_model.load_weights(weight_path) # load model weight
else:
    print("Denoiser function: use DnCNN trained on CT images.")
    # use dncnn_denoiser_ct function as input to MACE
    denoiser_func = dncnn_denoiser_ct
    denoiser_model_path = os.path.join(data_param_path, 'model_dncnn_video')
    denoiser_model = denoiser_utils.DenoiserCT(checkpoint_dir=denoiser_model_path)


################ Perform MACE reconstruction
print("Performing MACE reconstruction ...")
recon_mace = mbircone.mace.mace3D(sino_noisy, angles, dist_source_detector, magnification,
        denoiser=denoiser_func, denoiser_args=(denoiser_model,),
        max_admm_itr=max_admm_itr, prior_weight=prior_weight,
        delta_pixel_detector=delta_pixel_detector,
        weight_type='transmission')


recon_shape = recon_mace.shape
print("Reconstruction shape = ",recon_shape)
################ Post-process Reconstruction results
print("Post processing MACE reconstruction results ...")
# Output image and results directory
os.makedirs(output_dir, exist_ok=True)
# Save recon results as a numpy array
np.save(os.path.join(output_dir,"recon_mace.npy"), recon_mace)

# Plot sinogram data
demo_utils.plot_image(sino_noisy[0],title='sinogram view 0, noise level=0.05',filename=os.path.join(output_dir,'sino_noisy.png'),vmin=0,vmax=4)
demo_utils.plot_image(sino[0],title='clean sinogram view 0',filename=os.path.join(output_dir,'sino_clean.png'),vmin=0,vmax=4)
demo_utils.plot_image(noise[0],title='sinogram additive Gaussian noise,  view 0',filename=os.path.join(output_dir,'sino_transmission_noise.png'),vmin=-0.08,vmax=0.08)

# Plot axial slices of phantom and recon
display_slices = [2, recon_shape[0]//2]
for display_slice in display_slices:
    demo_utils.plot_image(phantom[display_slice],title=f'phantom, axial slice {display_slice}',filename=os.path.join(output_dir,f'phantom_slice{display_slice}.png'),vmin=0,vmax=0.5)
    demo_utils.plot_image(recon_mace[display_slice],title=f'MACE reconstruction, axial slice {display_slice}',filename=os.path.join(output_dir,f'recon_mace_slice{display_slice}.png'),vmin=0,vmax=0.5)

# Plot 3D phantom and recon image volumes as gif images.
demo_utils.plot_gif(phantom,output_dir,'phantom',vmin=0,vmax=0.5)
demo_utils.plot_gif(recon_mace,output_dir,'recon_mace',vmin=0,vmax=0.5)


input("press Enter")
