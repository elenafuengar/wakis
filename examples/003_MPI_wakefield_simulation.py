# copyright ################################# #
# This file is part of the wakis Package.     #
# Copyright (c) CERN, 2024.                   #
# ########################################### #

import os
import numpy as np
import pyvista as pv
import matplotlib.pyplot as plt

from wakis import SolverFIT3D
from wakis import GridFIT3D 
from wakis import WakeSolver

from tqdm import tqdm

# ---------- MPI setup ------------
from mpi4py import MPI

comm = MPI.COMM_WORLD  # Get MPI communicator
rank = comm.Get_rank()  # Process ID
size = comm.Get_size()  # Total number of MPI processes

print(f"Process {rank} of {size} is running")

# ---------- Domain setup ---------

# Geometry & Materials
solid_1 = 'data/001_vacuum_cavity.stl'
solid_2 = 'data/001_lossymetal_shell.stl'

stl_solids = {'cavity': solid_1, 
              'shell': solid_2
              }

stl_materials = {'cavity': 'vacuum', 
                 'shell': [30, 1.0, 30] #[eps_r, mu_r, sigma[S/m]]
                 }

# Extract domain bounds from geometry
solids = pv.read(solid_1) + pv.read(solid_2)
xmin, xmax, ymin, ymax, zmin, zmax = solids.bounds

# Number of mesh cells
Nx = 80
Ny = 80
Nz = 141

# Adjust for MPI & ompute local Z-slice range
Nz += Nz%(size-1)
dz = (zmax - zmin) / Nz
z = np.linspace(zmin, zmax, Nz+1)

Nz_mpi = Nz // (size-1) 
zmin_mpi = (rank-1) * Nz_mpi * dz
zmax_mpi= rank * Nz_mpi * dz

print(f"Process {rank}: Handling Z range {zmin_mpi} to {zmax_mpi}")

# set grid and geometry
if rank == 0:
    grid = GridFIT3D(xmin, xmax, ymin, ymax, zmin, zmax, 
                    Nx, Ny, Nz, 
                    stl_solids=stl_solids, 
                    stl_materials=stl_materials,
                    stl_scale=1.0,
                    stl_rotate=[0,0,0],
                    stl_translate=[0,0,0],
                    verbose=1)
else:
    grid = GridFIT3D(xmin, xmax, ymin, ymax, 
                        zmin_mpi, zmax_mpi, 
                        Nx, Ny, Nz_mpi, 
                        stl_solids=stl_solids, 
                        stl_materials=stl_materials,
                        stl_scale=1.0,
                        stl_rotate=[0,0,0],
                        stl_translate=[0,0,0],
                        verbose=1)
# BONUS: Visualize grid - Uncomment for plotting!
# grid.inspect(add_stl=[solid_1, solid_2], stl_opacity=1.0)

# BONUS: Visualize imported solids - Uncomment for plotting!
#grid.plot_solids()

# ------------ Beam source & Wake ----------------
# Beam parameters
sigmaz = 10e-2      #[m] -> 2 GHz
q = 1e-9            #[C]
beta = 1.0          # beam beta 
xs = 0.             # x source position [m]
ys = 0.             # y source position [m]
xt = 0.             # x test position [m]
yt = 0.             # y test position [m]
# [DEFAULT] tinj = 8.53*sigmaz/c_light  # injection time offset [s] 

# Simualtion
wakelength = 10. # [m]
add_space = 10   # no. cells to skip from boundaries - removes BC artifacts

wake = WakeSolver(q=q, 
                  sigmaz=sigmaz, 
                  beta=beta,
                  xsource=xs, ysource=ys, 
                  xtest=xt, ytest=yt,
                  add_space=add_space, 
                  results_folder='001_results/',
                  Ez_file='001_results/001_Ez.h5')

# ----------- Solver & Simulation ----------
# boundary conditions``
bc_low=['pec', 'pec', 'pec']
bc_high=['pec', 'pec', 'pec']

# on-the-fly plotting parameters
if not os.path.exists('001_img/'): 
    os.mkdir('001_img/')

plotkw2D = {'title':'001_img/Ez', 
            'add_patch':'cavity', 'patch_alpha':1.0,
            'patch_reverse' : True,  # patch logical_not('cavity')
            'vmin':-1e3, 'vmax':1e3, # colormap limits
            'cmap': 'rainbow',
            'plane': [int(Nx/2),                       # x
                      slice(0, Ny),                    # y
                      slice(add_space, -add_space)]}   # z

# Solver setup
solver = SolverFIT3D(grid, wake,
                    bc_low=bc_low, 
                    bc_high=bc_high, 
                    use_stl=True, 
                    bg='pec' # Background material
                    )
# [TODO]: domain should be split after the tensors are built 
# to avoid issues with boundary conditions / geometry
# Maybe need to add >1 ghost cells

# Solver run
'''
solver.wakesolve(wakelength=wakelength, 
                 add_space=add_space,
                 plot=True, # turn False for speedup
                 plot_every=30, plot_until=3000, **plotkw2D
                 )
'''
from wakis.sources import Beam
beam = Beam(q=q, sigmaz=sigmaz, beta=beta,
            xsource=xs, ysource=ys)

Nt = 1/solver.dt * (wake.wakelength + wake.ti*wake.v \
             + (solver.z.max()-solver.z.min()))/wake.v 

for n in tqdm(range(Nt)):

    beam.update_mpi(solver, n*solver.dt, zmin, z)

    solver.one_step()

    #Communicate slices [TODO]


# ----------- 1d plot results --------------------
# Plot longitudinal wake potential and impedance
fig1, ax = plt.subplots(1,2, figsize=[12,4], dpi=150)
ax[0].plot(wake.s*1e2, wake.WP, c='r', lw=1.5, label='Wakis')
ax[0].set_xlabel('s [cm]')
ax[0].set_ylabel('Longitudinal wake potential [V/pC]', color='r')
ax[0].legend()
ax[0].set_xlim(xmax=wakelength*1e2)

ax[1].plot(wake.f*1e-9, np.abs(wake.Z), c='b', lw=1.5, label='Wakis')
ax[1].set_xlabel('f [GHz]')
ax[1].set_ylabel('Longitudinal impedance [Abs][$\Omega$]', color='b')
ax[1].legend()

fig1.tight_layout()
fig1.savefig('001_results/001_longitudinal.png')
#plt.show()

# Plot transverse x wake potential and impedance
fig2, ax = plt.subplots(1,2, figsize=[12,4], dpi=150)
ax[0].plot(wake.s*1e2, wake.WPx, c='r', lw=1.5, label='Wakis')
ax[0].set_xlabel('s [cm]')
ax[0].set_ylabel('Transverse wake potential X [V/pC]', color='r')
ax[0].legend()
ax[0].set_xlim(xmax=wakelength*1e2)

ax[1].plot(wake.f*1e-9, np.abs(wake.Zx), c='b', lw=1.5, label='Wakis')
ax[1].set_xlabel('f [GHz]')
ax[1].set_ylabel('Transverse impedance X [Abs][$\Omega$]', color='b')
ax[1].legend()

fig2.tight_layout()
fig2.savefig('001_results/001_transverse_x.png')
#plt.show()

# Plot transverse y wake potential and impedance
fig3, ax = plt.subplots(1,2, figsize=[12,4], dpi=150)
ax[0].plot(wake.s*1e2, wake.WPy, c='r', lw=1.5, label='Wakis')
ax[0].set_xlabel('s [cm]')
ax[0].set_ylabel('Transverse wake potential Y [V/pC]', color='r')
ax[0].legend()
ax[0].set_xlim(xmax=wakelength*1e2)

ax[1].plot(wake.f*1e-9, np.abs(wake.Zy), c='b', lw=1.5, label='Wakis')
ax[1].set_xlabel('f [GHz]')
ax[1].set_ylabel('Transverse impedance Y [Abs][$\Omega$]', color='b')
ax[1].legend()

fig3.tight_layout()
fig3.savefig('001_results/001_transverse_y.png')
#plt.show()

# Plot Electric field component in 2D using imshow
solver.plot1D(field='E', component='z', 
              line='z', pos=0.5, xscale='linear', yscale='linear',
              off_screen=True, title='001_img/Ez1d')
#plt.show()

# ----------- 2d plots results --------------------
from matplotlib.colors import LinearSegmentedColormap
cmap = LinearSegmentedColormap.from_list('name', plt.cm.jet(np.linspace(0.1, 0.9))) # CST's colormap

# Plot Electric field component in 2D using imshow
solver.plot2D(field='E', component='z', 
              plane='XY', pos=0.5, 
              cmap=cmap, vmin=-500, vmax=500., interpolation='hanning',
              add_patch='cavity', patch_reverse=True, patch_alpha=0.8, 
              off_screen=True, title='001_img/Ez2d')
